use std::collections::{BTreeMap, VecDeque};
use std::env;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, RwLock, mpsc};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const VERSION: &str = env!("CARGO_PKG_VERSION");
const DEFAULT_LISTEN: &str = "127.0.0.1:9836";
const TARGET_INTERVAL_SECONDS: f64 = 0.250;
const STALE_AFTER: Duration = Duration::from_millis(750);
const WATCHDOG_TIMEOUT: Duration = Duration::from_millis(1500);
const QUERY_FIELDS: &str = "index,uuid,name,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,temperature.gpu,fan.speed,clocks.current.graphics,clocks.current.memory,pstate,pcie.link.gen.current,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max,clocks_event_reasons.active,clocks_event_reasons.gpu_idle,clocks_event_reasons.applications_clocks_setting,clocks_event_reasons.sw_power_cap,clocks_event_reasons.hw_slowdown,clocks_event_reasons.hw_thermal_slowdown,clocks_event_reasons.hw_power_brake_slowdown,clocks_event_reasons.sw_thermal_slowdown,clocks_event_reasons.sync_boost";

#[derive(Clone, Debug)]
struct Sample {
    index: u32,
    uuid: String,
    name: String,
    utilization_gpu: Option<f64>,
    utilization_memory: Option<f64>,
    memory_used_mib: Option<f64>,
    memory_total_mib: Option<f64>,
    power_watts: Option<f64>,
    temperature_celsius: Option<f64>,
    fan_percent: Option<f64>,
    graphics_clock_mhz: Option<f64>,
    memory_clock_mhz: Option<f64>,
    pstate: Option<f64>,
    pcie_generation_current: Option<f64>,
    pcie_generation_max: Option<f64>,
    pcie_width_current: Option<f64>,
    pcie_width_max: Option<f64>,
    throttle_mask: Option<f64>,
    throttle_gpu_idle: Option<f64>,
    throttle_applications_clocks: Option<f64>,
    throttle_software_power_cap: Option<f64>,
    throttle_hardware_slowdown: Option<f64>,
    throttle_hardware_thermal: Option<f64>,
    throttle_hardware_power_brake: Option<f64>,
    throttle_software_thermal: Option<f64>,
    throttle_sync_boost: Option<f64>,
}

#[derive(Clone, Copy, Debug)]
struct TimedPoint {
    at: Instant,
    utilization_gpu: Option<f64>,
    utilization_memory: Option<f64>,
    power_watts: Option<f64>,
}

#[derive(Clone, Copy, Debug, Default)]
struct Summary {
    min: f64,
    max: f64,
    average: f64,
    count: usize,
}

impl Summary {
    fn from_values(values: impl Iterator<Item = f64>) -> Self {
        let mut result = Summary {
            min: f64::INFINITY,
            max: f64::NEG_INFINITY,
            average: 0.0,
            count: 0,
        };
        let mut sum = 0.0;
        for value in values {
            result.min = result.min.min(value);
            result.max = result.max.max(value);
            sum += value;
            result.count += 1;
        }
        if result.count > 0 {
            result.average = sum / result.count as f64;
        }
        result
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct RollingSummaries {
    utilization_gpu: Summary,
    utilization_memory: Summary,
    power_watts: Summary,
}

#[derive(Debug)]
struct GpuSeries {
    latest: Sample,
    last_update: Instant,
    last_update_unix: f64,
    last_interval_seconds: f64,
    points: VecDeque<TimedPoint>,
    rolling: RollingSummaries,
}

impl GpuSeries {
    fn new(sample: Sample, now: Instant, unix_now: f64) -> Self {
        let mut result = Self {
            latest: sample,
            last_update: now,
            last_update_unix: unix_now,
            last_interval_seconds: 0.0,
            points: VecDeque::new(),
            rolling: RollingSummaries::default(),
        };
        result.push_point(now);
        result
    }

    fn update(&mut self, sample: Sample, now: Instant, unix_now: f64) {
        self.last_interval_seconds = now.duration_since(self.last_update).as_secs_f64();
        self.latest = sample;
        self.last_update = now;
        self.last_update_unix = unix_now;
        self.push_point(now);
    }

    fn push_point(&mut self, now: Instant) {
        self.points.push_back(TimedPoint {
            at: now,
            utilization_gpu: self.latest.utilization_gpu,
            utilization_memory: self.latest.utilization_memory,
            power_watts: self.latest.power_watts,
        });
        while self
            .points
            .front()
            .is_some_and(|point| now.duration_since(point.at) > Duration::from_secs(1))
        {
            self.points.pop_front();
        }
        self.rolling = RollingSummaries {
            utilization_gpu: Summary::from_values(
                self.points.iter().filter_map(|point| point.utilization_gpu),
            ),
            utilization_memory: Summary::from_values(
                self.points
                    .iter()
                    .filter_map(|point| point.utilization_memory),
            ),
            power_watts: Summary::from_values(
                self.points.iter().filter_map(|point| point.power_watts),
            ),
        };
    }
}

#[derive(Debug)]
struct ExporterState {
    started: Instant,
    process_up: bool,
    last_sample: Option<Instant>,
    samples_total: u64,
    parse_errors_total: u64,
    sampler_restarts_total: u64,
    watchdog_timeouts_total: u64,
    gpus: BTreeMap<u32, GpuSeries>,
}

impl ExporterState {
    fn new() -> Self {
        Self {
            started: Instant::now(),
            process_up: false,
            last_sample: None,
            samples_total: 0,
            parse_errors_total: 0,
            sampler_restarts_total: 0,
            watchdog_timeouts_total: 0,
            gpus: BTreeMap::new(),
        }
    }

    fn record_sample(&mut self, sample: Sample, now: Instant, unix_now: f64) {
        self.process_up = true;
        self.last_sample = Some(now);
        self.samples_total += 1;
        match self.gpus.get_mut(&sample.index) {
            Some(series) => series.update(sample, now, unix_now),
            None => {
                self.gpus
                    .insert(sample.index, GpuSeries::new(sample, now, unix_now));
            }
        }
    }

    fn record_parse_error(&mut self) {
        self.parse_errors_total += 1;
    }

    fn record_sampler_failure(&mut self, watchdog_timeout: bool) {
        self.process_up = false;
        self.sampler_restarts_total += 1;
        if watchdog_timeout {
            self.watchdog_timeouts_total += 1;
        }
    }

    fn sample_age(&self, now: Instant) -> Option<Duration> {
        self.last_sample.map(|sample| now.duration_since(sample))
    }

    fn effective_up(&self, now: Instant) -> bool {
        self.process_up && self.sample_age(now).is_some_and(|age| age <= STALE_AFTER)
    }
}

fn field<'a>(fields: &'a [&str], index: usize) -> Result<&'a str, String> {
    fields
        .get(index)
        .map(|value| value.trim())
        .ok_or_else(|| format!("missing field {index}"))
}

fn parse_number(value: &str) -> Option<f64> {
    let value = value.trim();
    if value.is_empty() || value.eq_ignore_ascii_case("N/A") || value == "[Not Supported]" {
        None
    } else {
        value.parse::<f64>().ok()
    }
}

fn parse_pstate(value: &str) -> Option<f64> {
    let value = value.trim();
    value
        .strip_prefix('P')
        .or_else(|| value.strip_prefix('p'))
        .and_then(parse_number)
}

fn parse_mask(value: &str) -> Option<f64> {
    let value = value.trim();
    if value.eq_ignore_ascii_case("N/A") {
        return None;
    }
    value
        .strip_prefix("0x")
        .and_then(|hex| u64::from_str_radix(hex, 16).ok())
        .map(|number| number as f64)
        .or_else(|| parse_number(value))
}

fn parse_active(value: &str) -> Option<f64> {
    match value.trim() {
        "Active" => Some(1.0),
        "Not Active" => Some(0.0),
        _ => None,
    }
}

fn parse_line(line: &str) -> Result<Sample, String> {
    let fields: Vec<&str> = line.split(',').collect();
    if fields.len() != 26 {
        return Err(format!("expected 26 fields, got {}", fields.len()));
    }
    let index = field(&fields, 0)?
        .parse::<u32>()
        .map_err(|_| "invalid GPU index".to_string())?;
    let uuid = field(&fields, 1)?.to_string();
    let name = field(&fields, 2)?.to_string();
    if uuid.is_empty() || name.is_empty() {
        return Err("empty GPU identity".to_string());
    }
    Ok(Sample {
        index,
        uuid,
        name,
        utilization_gpu: parse_number(field(&fields, 3)?),
        utilization_memory: parse_number(field(&fields, 4)?),
        memory_used_mib: parse_number(field(&fields, 5)?),
        memory_total_mib: parse_number(field(&fields, 6)?),
        power_watts: parse_number(field(&fields, 7)?),
        temperature_celsius: parse_number(field(&fields, 8)?),
        fan_percent: parse_number(field(&fields, 9)?),
        graphics_clock_mhz: parse_number(field(&fields, 10)?),
        memory_clock_mhz: parse_number(field(&fields, 11)?),
        pstate: parse_pstate(field(&fields, 12)?),
        pcie_generation_current: parse_number(field(&fields, 13)?),
        pcie_generation_max: parse_number(field(&fields, 14)?),
        pcie_width_current: parse_number(field(&fields, 15)?),
        pcie_width_max: parse_number(field(&fields, 16)?),
        throttle_mask: parse_mask(field(&fields, 17)?),
        throttle_gpu_idle: parse_active(field(&fields, 18)?),
        throttle_applications_clocks: parse_active(field(&fields, 19)?),
        throttle_software_power_cap: parse_active(field(&fields, 20)?),
        throttle_hardware_slowdown: parse_active(field(&fields, 21)?),
        throttle_hardware_thermal: parse_active(field(&fields, 22)?),
        throttle_hardware_power_brake: parse_active(field(&fields, 23)?),
        throttle_software_thermal: parse_active(field(&fields, 24)?),
        throttle_sync_boost: parse_active(field(&fields, 25)?),
    })
}

fn backoff_delay(attempt: u32) -> Duration {
    let multiplier = 1_u64 << attempt.min(4);
    Duration::from_millis(250 * multiplier)
}

fn unix_now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

fn spawn_sampler() -> std::io::Result<Child> {
    let binary = env::var("NVIDIA_SMI_PATH").unwrap_or_else(|_| "nvidia-smi".to_string());
    Command::new(binary)
        .arg(format!("--query-gpu={QUERY_FIELDS}"))
        .arg("--format=csv,noheader,nounits")
        .arg("--loop-ms=250")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
}

fn sampler_loop(shared: Arc<RwLock<ExporterState>>) {
    let mut failure_attempt = 0_u32;
    loop {
        let mut child = match spawn_sampler() {
            Ok(child) => child,
            Err(_) => {
                shared
                    .write()
                    .expect("state lock poisoned")
                    .record_sampler_failure(false);
                thread::sleep(backoff_delay(failure_attempt));
                failure_attempt = failure_attempt.saturating_add(1);
                continue;
            }
        };
        let stdout = match child.stdout.take() {
            Some(stdout) => stdout,
            None => {
                let _ = child.kill();
                let _ = child.wait();
                shared
                    .write()
                    .expect("state lock poisoned")
                    .record_sampler_failure(false);
                thread::sleep(backoff_delay(failure_attempt));
                failure_attempt = failure_attempt.saturating_add(1);
                continue;
            }
        };
        let (sender, receiver) = mpsc::channel::<String>();
        thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                match line {
                    Ok(line) => {
                        if sender.send(line).is_err() {
                            break;
                        }
                    }
                    Err(_) => break,
                }
            }
        });

        let mut received_valid_sample = false;
        let mut watchdog_timeout = false;
        loop {
            match receiver.recv_timeout(WATCHDOG_TIMEOUT) {
                Ok(line) => match parse_line(&line) {
                    Ok(sample) => {
                        received_valid_sample = true;
                        failure_attempt = 0;
                        shared.write().expect("state lock poisoned").record_sample(
                            sample,
                            Instant::now(),
                            unix_now(),
                        );
                    }
                    Err(_) => shared
                        .write()
                        .expect("state lock poisoned")
                        .record_parse_error(),
                },
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    watchdog_timeout = true;
                    break;
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => break,
            }
        }
        let _ = child.kill();
        let _ = child.wait();
        shared
            .write()
            .expect("state lock poisoned")
            .record_sampler_failure(watchdog_timeout);
        if !received_valid_sample {
            failure_attempt = failure_attempt.saturating_add(1);
        }
        thread::sleep(backoff_delay(failure_attempt));
    }
}

fn escape_label(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('\n', "\\n")
        .replace('"', "\\\"")
}

fn gpu_labels(sample: &Sample) -> String {
    format!(
        "{{gpu_index=\"{}\",gpu_uuid=\"{}\",gpu_name=\"{}\"}}",
        sample.index,
        escape_label(&sample.uuid),
        escape_label(&sample.name)
    )
}

fn metric(out: &mut String, name: &str, labels: &str, value: Option<f64>, scale: f64) {
    if let Some(value) = value {
        out.push_str(&format!("{name}{labels} {}\n", value * scale));
    }
}

fn summary_metrics(out: &mut String, base: &str, labels: &str, summary: Summary) {
    if summary.count == 0 {
        return;
    }
    out.push_str(&format!("{base}_min{labels} {}\n", summary.min));
    out.push_str(&format!("{base}_max{labels} {}\n", summary.max));
    out.push_str(&format!("{base}_average{labels} {}\n", summary.average));
    out.push_str(&format!("{base}_samples{labels} {}\n", summary.count));
}

fn render_metrics(state: &ExporterState, now: Instant) -> String {
    let mut out = String::with_capacity(16 * 1024);
    out.push_str(
        "# HELP supermicro_gpu_exporter_build_info Build information for the custom exporter.\n",
    );
    out.push_str("# TYPE supermicro_gpu_exporter_build_info gauge\n");
    out.push_str(&format!(
        "supermicro_gpu_exporter_build_info{{version=\"{}\"}} 1\n",
        VERSION
    ));
    out.push_str("# HELP supermicro_gpu_sampler_up Whether the persistent sampler is producing fresh data.\n");
    out.push_str("# TYPE supermicro_gpu_sampler_up gauge\n");
    out.push_str(&format!(
        "supermicro_gpu_sampler_up {}\n",
        u8::from(state.effective_up(now))
    ));
    out.push_str(&format!(
        "supermicro_gpu_exporter_uptime_seconds {}\n",
        now.duration_since(state.started).as_secs_f64()
    ));
    out.push_str(&format!(
        "supermicro_gpu_sampler_target_interval_seconds {}\n",
        TARGET_INTERVAL_SECONDS
    ));
    if let Some(age) = state.sample_age(now) {
        out.push_str(&format!(
            "supermicro_gpu_sample_age_seconds {}\n",
            age.as_secs_f64()
        ));
    }
    out.push_str(&format!(
        "supermicro_gpu_samples_total {}\n",
        state.samples_total
    ));
    out.push_str(&format!(
        "supermicro_gpu_parse_errors_total {}\n",
        state.parse_errors_total
    ));
    out.push_str(&format!(
        "supermicro_gpu_sampler_restarts_total {}\n",
        state.sampler_restarts_total
    ));
    out.push_str(&format!(
        "supermicro_gpu_watchdog_timeouts_total {}\n",
        state.watchdog_timeouts_total
    ));

    for series in state.gpus.values() {
        let sample = &series.latest;
        let labels = gpu_labels(sample);
        out.push_str(&format!("supermicro_gpu_info{labels} 1\n"));
        out.push_str(&format!(
            "supermicro_gpu_sample_timestamp_seconds{labels} {}\n",
            series.last_update_unix
        ));
        out.push_str(&format!(
            "supermicro_gpu_sample_age_seconds_per_gpu{labels} {}\n",
            now.duration_since(series.last_update).as_secs_f64()
        ));
        if series.last_interval_seconds > 0.0 {
            out.push_str(&format!(
                "supermicro_gpu_sample_interval_seconds{labels} {}\n",
                series.last_interval_seconds
            ));
        }
        metric(
            &mut out,
            "supermicro_gpu_utilization_percent",
            &labels,
            sample.utilization_gpu,
            1.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_memory_utilization_percent",
            &labels,
            sample.utilization_memory,
            1.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_memory_used_bytes",
            &labels,
            sample.memory_used_mib,
            1024.0 * 1024.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_memory_total_bytes",
            &labels,
            sample.memory_total_mib,
            1024.0 * 1024.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_power_draw_watts",
            &labels,
            sample.power_watts,
            1.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_temperature_celsius",
            &labels,
            sample.temperature_celsius,
            1.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_fan_speed_percent",
            &labels,
            sample.fan_percent,
            1.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_graphics_clock_hertz",
            &labels,
            sample.graphics_clock_mhz,
            1_000_000.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_memory_clock_hertz",
            &labels,
            sample.memory_clock_mhz,
            1_000_000.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_performance_state",
            &labels,
            sample.pstate,
            1.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_pcie_link_generation",
            &labels,
            sample.pcie_generation_current,
            1.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_pcie_link_generation_max",
            &labels,
            sample.pcie_generation_max,
            1.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_pcie_link_width",
            &labels,
            sample.pcie_width_current,
            1.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_pcie_link_width_max",
            &labels,
            sample.pcie_width_max,
            1.0,
        );
        metric(
            &mut out,
            "supermicro_gpu_throttle_reasons_mask",
            &labels,
            sample.throttle_mask,
            1.0,
        );

        let reasons = [
            ("gpu_idle", sample.throttle_gpu_idle),
            ("applications_clocks", sample.throttle_applications_clocks),
            ("software_power_cap", sample.throttle_software_power_cap),
            ("hardware_slowdown", sample.throttle_hardware_slowdown),
            ("hardware_thermal", sample.throttle_hardware_thermal),
            ("hardware_power_brake", sample.throttle_hardware_power_brake),
            ("software_thermal", sample.throttle_software_thermal),
            ("sync_boost", sample.throttle_sync_boost),
        ];
        for (reason, value) in reasons {
            if let Some(value) = value {
                let reason_labels = format!(
                    "{{gpu_index=\"{}\",gpu_uuid=\"{}\",gpu_name=\"{}\",reason=\"{}\"}}",
                    sample.index,
                    escape_label(&sample.uuid),
                    escape_label(&sample.name),
                    reason
                );
                out.push_str(&format!(
                    "supermicro_gpu_throttle_reason_active{reason_labels} {value}\n"
                ));
            }
        }

        summary_metrics(
            &mut out,
            "supermicro_gpu_utilization_1s_percent",
            &labels,
            series.rolling.utilization_gpu,
        );
        summary_metrics(
            &mut out,
            "supermicro_gpu_memory_utilization_1s_percent",
            &labels,
            series.rolling.utilization_memory,
        );
        summary_metrics(
            &mut out,
            "supermicro_gpu_power_draw_1s_watts",
            &labels,
            series.rolling.power_watts,
        );
    }
    out
}

fn http_response(mut stream: TcpStream, shared: &Arc<RwLock<ExporterState>>) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
    let mut request = [0_u8; 4096];
    let bytes = match stream.read(&mut request) {
        Ok(bytes) => bytes,
        Err(_) => return,
    };
    let first_line = String::from_utf8_lossy(&request[..bytes]);
    let path = first_line
        .lines()
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .unwrap_or("/");
    let (status, content_type, body) = match path {
        "/metrics" => (
            "200 OK",
            "text/plain; version=0.0.4; charset=utf-8",
            render_metrics(&shared.read().expect("state lock poisoned"), Instant::now()),
        ),
        "/-/healthy" => (
            "200 OK",
            "text/plain; charset=utf-8",
            "healthy\n".to_string(),
        ),
        "/-/ready" => {
            let ready = shared
                .read()
                .expect("state lock poisoned")
                .effective_up(Instant::now());
            if ready {
                ("200 OK", "text/plain; charset=utf-8", "ready\n".to_string())
            } else {
                (
                    "503 Service Unavailable",
                    "text/plain; charset=utf-8",
                    "sampler has no fresh data\n".to_string(),
                )
            }
        }
        _ => (
            "404 Not Found",
            "text/plain; charset=utf-8",
            "not found\n".to_string(),
        ),
    };
    let response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes());
}

fn healthcheck(address: &str) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(
        &address.parse().expect("invalid healthcheck address"),
        Duration::from_secs(2),
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    if stream
        .write_all(b"GET /-/healthy HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = [0_u8; 64];
    stream
        .read(&mut response)
        .is_ok_and(|bytes| String::from_utf8_lossy(&response[..bytes]).contains(" 200 "))
}

fn main() {
    let mut listen =
        env::var("GPU_EXPORTER_LISTEN_ADDRESS").unwrap_or_else(|_| DEFAULT_LISTEN.to_string());
    let mut check = false;
    let mut arguments = env::args().skip(1);
    while let Some(argument) = arguments.next() {
        match argument.as_str() {
            "--listen-address" => {
                listen = arguments.next().expect("--listen-address requires a value")
            }
            "--check" => check = true,
            "--version" => {
                println!("supermicro-gpu-exporter {VERSION}");
                return;
            }
            _ => panic!("unknown argument: {argument}"),
        }
    }
    if check {
        std::process::exit(if healthcheck(&listen) { 0 } else { 1 });
    }

    let shared = Arc::new(RwLock::new(ExporterState::new()));
    let sampler_state = Arc::clone(&shared);
    thread::spawn(move || sampler_loop(sampler_state));

    let listener = TcpListener::bind(&listen).unwrap_or_else(|error| {
        panic!("failed to listen on {listen}: {error}");
    });
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let request_state = Arc::clone(&shared);
                thread::spawn(move || http_response(stream, &request_state));
            }
            Err(error) => eprintln!("HTTP accept error: {error}"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const NORMAL_ROW: &str = "0, GPU-TEST-PRIMARY, NVIDIA GeForce RTX 3090, 71, 12, 4096, 24576, 312.5, 67, 64, 1695, 9751, P2, 3, 3, 16, 16, 0x0000000000000004, Not Active, Not Active, Active, Not Active, Not Active, Not Active, Not Active, Not Active";

    #[test]
    fn parses_normal_row() {
        let sample = parse_line(NORMAL_ROW).expect("normal row should parse");
        assert_eq!(sample.index, 0);
        assert_eq!(sample.uuid, "GPU-TEST-PRIMARY");
        assert_eq!(sample.utilization_gpu, Some(71.0));
        assert_eq!(sample.memory_used_mib, Some(4096.0));
        assert_eq!(sample.pstate, Some(2.0));
        assert_eq!(sample.throttle_software_power_cap, Some(1.0));
    }

    #[test]
    fn accepts_na_values() {
        let mut fields: Vec<String> = NORMAL_ROW.split(',').map(str::to_string).collect();
        fields[7] = " N/A".to_string();
        fields[9] = " N/A".to_string();
        fields[17] = " N/A".to_string();
        let sample = parse_line(&fields.join(",")).expect("N/A row should parse");
        assert_eq!(sample.power_watts, None);
        assert_eq!(sample.fan_percent, None);
        assert_eq!(sample.throttle_mask, None);
    }

    #[test]
    fn rejects_malformed_rows() {
        assert!(parse_line("0, too, short").is_err());
        assert!(parse_line(&NORMAL_ROW.replacen("0,", "bad,", 1)).is_err());
    }

    #[test]
    fn dual_gpu_reversed_order_keeps_identity() {
        let gpu_one = NORMAL_ROW
            .replacen("0,", "1,", 1)
            .replace("GPU-TEST-PRIMARY", "GPU-TEST-SECONDARY");
        let now = Instant::now();
        let mut state = ExporterState::new();
        state.record_sample(parse_line(&gpu_one).unwrap(), now, 1.0);
        state.record_sample(parse_line(NORMAL_ROW).unwrap(), now, 1.0);
        let metrics = render_metrics(&state, now);
        assert_eq!(state.gpus.len(), 2);
        assert!(metrics.contains("gpu_index=\"0\",gpu_uuid=\"GPU-TEST-PRIMARY\""));
        assert!(metrics.contains("gpu_index=\"1\",gpu_uuid=\"GPU-TEST-SECONDARY\""));
    }

    #[test]
    fn sampler_failure_marks_down_and_backoff_is_bounded() {
        let mut state = ExporterState::new();
        let now = Instant::now();
        state.record_sample(parse_line(NORMAL_ROW).unwrap(), now, 1.0);
        state.record_sampler_failure(false);
        assert!(!state.effective_up(now));
        assert_eq!(state.sampler_restarts_total, 1);
        assert_eq!(backoff_delay(0), Duration::from_millis(250));
        assert_eq!(backoff_delay(50), Duration::from_secs(4));
    }

    #[test]
    fn stale_data_is_retained_but_sampler_is_down() {
        let now = Instant::now();
        let old = now - Duration::from_secs(2);
        let mut state = ExporterState::new();
        state.record_sample(parse_line(NORMAL_ROW).unwrap(), old, 1.0);
        assert!(!state.effective_up(now));
        let metrics = render_metrics(&state, now);
        assert!(metrics.contains("supermicro_gpu_sampler_up 0"));
        assert!(metrics.contains("supermicro_gpu_utilization_percent"));
    }
}
