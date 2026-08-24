.PHONY: install start stop status password

install:
	@if [ ! -f .env ]; then scripts/configure-host --interactive --apply; fi
	@sudo ./scripts/install-system.sh
	@printf '\nGrafana admin password:\n'
	@scripts/host_config.py password
	@printf '\nThe password is stored in ignored runtime/secrets/grafana-admin-password (mode 0600).\n'
	@printf 'Start on demand with: sudo systemctl start supermicro-observability\n'

start:
	@sudo systemctl start supermicro-observability

stop:
	@sudo systemctl stop supermicro-observability

status:
	@sudo systemctl status supermicro-observability

password:
	@scripts/host_config.py password
