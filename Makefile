.DEFAULT_GOAL := help

.PHONY: help configure run stop status password bind install-system install

help:
	@printf '%s\n' \
		'Checkout-local operation (default):' \
		'  make run                         configure if needed and start' \
		'  make stop                        stop checkout-local monitoring' \
		'  make status                      show checkout-local containers' \
		'  make configure                   interactively update local config' \
		'  make bind ADDRESS=PRIVATE_IP     set the stopped local Grafana bind' \
		'  make password                    print the local Grafana password' \
		'' \
		'Optional system installation:' \
		'  make install-system              install under /opt, /etc, and /var/lib'

configure:
	@scripts/source-control configure

run:
	@scripts/source-control run

stop:
	@scripts/source-control stop

status:
	@scripts/source-control status

password:
	@scripts/source-control password

bind:
	@test -n "$(ADDRESS)" || { echo 'usage: make bind ADDRESS=PRIVATE_IP' >&2; exit 2; }
	@scripts/source-control bind "$(ADDRESS)"

install-system:
	@if [ ! -f .env ] && [ ! -f /etc/supermicro-observability/config.env ]; then scripts/source-control configure; fi
	@sudo ./scripts/install-system.sh

install: install-system
