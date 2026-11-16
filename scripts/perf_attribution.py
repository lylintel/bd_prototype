import argparse
import json
from pathlib import Path

from scripts.synthetic_design import benchmark


def capture(output, context, plugins=(), collected=None):
    results = [benchmark(samples=11, gc_mode=mode) for mode in ("on", "off")]
    report = {"context": context, "pytest_plugins": list(plugins), "tests_collected": collected, "results": results}
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for result in results:
        print(f"PERF {context} GC={result['gc_mode']} median={result['median_ms']:.3f} max={result['max_ms']:.3f} ms", flush=True)
    return report


def pytest_addoption(parser):
    parser.addoption("--perf-attribution", default=None)
    parser.addoption("--perf-context", default="pytest-tail")


def pytest_collection_modifyitems(session, config, items):
    if not config.getoption("--perf-attribution"):
        return
    import pytest

    class AttributionItem(pytest.Item):
        def runtest(self):
            plugins = sorted({getattr(plugin, "__name__", type(plugin).__name__) for plugin in config.pluginmanager.get_plugins()})
            capture(config.getoption("--perf-attribution"), config.getoption("--perf-context"), plugins, session.testscollected)

        def reportinfo(self):
            return self.path, 0, "GC and instrumentation attribution"

    items.append(AttributionItem.from_parent(session, name="perf-attribution"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded GC and instrumentation attribution")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    capture(args.output, "standalone-cli")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())