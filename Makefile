.PHONY: all assets clean clean-assets flipper openwrt paper submodules test

all: test

submodules:
	git submodule update --init --recursive

test:
	python3 -m unittest discover -s tests -v
	./src/flipper/ethernet_lab/tests/run.sh

assets:
	./scripts/generate-public-assets

clean-assets:
	./scripts/clean-asset-metadata

flipper:
	./scripts/build-flipper-app

openwrt:
	./scripts/build-openwrt-module

paper:
	./scripts/generate-pdf

clean:
	find build -depth -mindepth 1 ! -name .gitkeep -delete
