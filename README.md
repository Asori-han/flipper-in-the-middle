# Flipper in the Middle
Superior degree of [Network Computer System Administration](https://www.boe.es/diario_boe/txt.php?id=BOE-A-2009-18355) final project about data leaks on public administration by Jansu Soria (aka [Asori-han](https://github.com/Asori-han)) from [CIFP Politècnic Llevant](https://www.politecnicllevant.cat/).

## Requisites
* [Ruby](https://www.ruby-lang.org)
* [Gnuplot](http://www.gnuplot.info/)

## Usage

```bash
# Generate project paper from Asciidoctor code
./scripts/generate-pdf
```

## Flipper Zero toolkit

[`src/flipper/ethernet_lab`](src/flipper/ethernet_lab) contains the publishable
source for the scriptable Flipper Zero and W5500 demo application. Its `.eth`
files reproduce link, ARP, ICMP payload-pattern and clear-text HTTP experiments.
See the app README for wiring, build instructions and the command reference.

## Paper sources

The paper's AsciiDoc sources and technical analysis are maintained under
[`docs/paper/`](docs/paper/index.adoc); the generated PDF is linked below.

## Downloads
* [Paper](https://asori.es/public/flipper-in-the-middle/flipper-in-the-middle.pdf)
* [Presentation](https://asori.es/public/flipper-in-the-middle/flipper-in-the-middle.ppsx)

## Development setup

```bash
git clone --recurse-submodules git@github.com:Asori-han/flipper-in-the-middle.git
cd flipper-in-the-middle
python3 -m venv build/cache/venv
build/cache/venv/bin/pip install -r requirements/lab.txt
make test
make assets
```

For an existing checkout, initialize the pinned external repositories with:

```bash
git submodule update --init --recursive
```

### Docker

`docker/general.Dockerfile` provides the general Python and Asciidoctor environment.
Compose also defines dedicated images for Flipper firmware 1.4.3 and OpenWrt
22.03.4. After cloning recursively, build the three environments once:

```bash
docker compose build
```

Run disposable containers for each operation:

```bash
docker compose run --rm general make test
docker compose run --rm general make assets
docker compose run --rm general make paper
docker compose run --rm flipper
docker compose run --rm openwrt
```

The repository is bind-mounted at `/workspace`; generated results remain
available on the host under `build/`. OpenWrt builds on a named,
case-sensitive volume that survives disposable containers and image updates,
while Flipper keeps its downloaded toolchain and intermediate files in the
ignored firmware submodule worktree.

## Repository layout

| Path | Contents |
| --- | --- |
| `src/lab/` | Capture, sanitization, decoding, export and visualization tools |
| `src/flipper/ethernet_lab/` | Ethernet Lab application for Flipper Zero |
| `src/openwrt/mt7628-phy-lab/` | OpenWrt package and recovered module source |
| `tests/` | Offline tests for the analysis toolkit |
| `data/captures/` | Sanitized NPZ captures suitable for publication |
| `docs/` | Technical reference, experiments, diagrams and paper sources |
| `docs/assets/` | Source assets used by the paper and presentation |
| `scripts/` | Reproducible project automation |
| `data/local/` | Unprocessed local captures and run evidence, ignored by Git |
| `third_party/` | Pinned OpenWrt and Flipper firmware submodules |
| `build/` | Regenerable local results, binaries and caches |

Files under `build/` and `data/local/` are ignored by Git. `make assets`
rebuilds public Ethernet and PoE figures, HEX transcripts, JSON reports and
PCAPNG files from the sanitized captures.

Python visualization code remains language-neutral. Spanish text rendered in
figures and animations is maintained separately in
[`docs/plot-labels.es.json`](docs/plot-labels.es.json), so wording can be
edited without changing plotting logic.
The Mango OpenWrt build configuration lives alongside its package source in
[`src/openwrt/gl-mt300n-v2.config`](src/openwrt/gl-mt300n-v2.config).

## Flipper Zero build

The firmware used for the hardware tests is pinned to official release 1.4.3.
Build the application from the project root:

```bash
scripts/build-flipper-app
```

The wrapper temporarily links the application into the firmware checkout's
`applications_user/` directory, invokes `fbt`, removes the link and copies
the resulting FAP to `build/flipper/ethernet_lab.fap`. The firmware
submodule remains unchanged.

The synchronized DOS1102, Logic 2 and Flipper capture environment is prepared
and run with:

```bash
scripts/setup-demo-capture
scripts/run-demo-capture increment --duration 30
```

Runs are written to `data/local/evidence/demo-runs/`.

## MT7628 kernel module

Build `mt7628_phy_lab.ko` from the pinned OpenWrt source in the dedicated
container. The persistent `openwrt-build` volume retains the toolchain and
kernel build for subsequent runs.

```bash
docker compose build openwrt
docker compose run --rm openwrt
```

The C source recovered from the project history is kept alongside its OpenWrt
package. The module and package are written to `build/openwrt/`; source and
build instructions are documented in
[`src/openwrt/mt7628-phy-lab/`](src/openwrt/mt7628-phy-lab/).

Before committing images or Office documents under `docs/assets/`, remove
embedded author, location, camera and editing metadata with:

```bash
make clean-assets
```

Commands under `scripts/` intentionally omit language extensions. They are
executable project interfaces, so callers do not depend on whether an
implementation uses Python, POSIX shell, or another language.
