.PHONY: install start stop restart status logs password configure bind uninstall purge

install:
	@if [ ! -f .env ] && [ ! -f /etc/supermicro-observability/config.env ]; then scripts/configure-host --interactive --apply; fi
	@sudo ./scripts/install-system.sh

start:
	@sudo supermicro-observability start

stop:
	@sudo supermicro-observability stop

restart:
	@sudo supermicro-observability restart

status:
	@sudo supermicro-observability status

logs:
	@sudo supermicro-observability logs

password:
	@sudo supermicro-observability password

configure:
	@sudo supermicro-observability configure

bind:
	@test -n "$(ADDRESS)" || { echo 'usage: make bind ADDRESS=PRIVATE_IP' >&2; exit 2; }
	@sudo supermicro-observability bind "$(ADDRESS)"

uninstall:
	@sudo supermicro-observability uninstall

purge:
	@sudo supermicro-observability purge
