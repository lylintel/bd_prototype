import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bdstudio.ai_eval import catalog
from core.ops import typed_endpoint
from core.resolve import resolve


SETUPS = {
    "counter_compare_basic": ({"counter": {"WIDTH": 8}, "compare_eq": {"WIDTH": 8, "THRESHOLD": 9}},
                              [("counter.count", "compare_eq.value"), ("@clk", "counter.clk"), ("@rst", "counter.rst"), ("compare_eq.match", "@match")]),
    "synchronous_fifo": ({"bd_sync_fifo": {"WIDTH": 8, "DEPTH": 8}}, []),
    "synchronize_control": ({"bd_sync_2ff": {}}, []),
    "edge_pulses": ({"bd_edge_detect": {}}, []),
    "clock_tick": ({"bd_clock_divider": {"HALF_PERIOD": 4}}, []),
    "debounce_button": ({"bd_debounce": {"STABLE_CYCLES": 8}}, []),
    "serial_shift": ({"bd_shift_register": {"WIDTH": 8}}, []),
    "stream_register": ({"bd_stream_slice": {"WIDTH": 8}}, []),
    "select_two": ({"bd_mux2": {"WIDTH": 8}}, []),
    "dual_port_memory": ({"bd_simple_dual_port_ram": {"WIDTH": 8, "ADDR_WIDTH": 4}}, []),
    "counter_event_chain": ({"bd_counter": {"WIDTH": 8}, "bd_compare": {"WIDTH": 8}, "bd_edge_detect": {}, "bd_sync_2ff": {}},
                            [("bd_counter.count", "bd_compare.left_data"), ("bd_compare.equal", "bd_edge_detect.signal_in"), ("bd_edge_detect.rising", "bd_sync_2ff.async_in")]),
    "fifo_register_chain": ({"bd_sync_fifo": {"WIDTH": 8}, "bd_stream_slice": {"WIDTH": 8}, "bd_mux2": {"WIDTH": 8}},
                            [("bd_sync_fifo.m_data", "bd_stream_slice.s_data"), ("bd_sync_fifo.m_valid", "bd_stream_slice.s_valid"),
                             ("bd_stream_slice.s_ready", "bd_sync_fifo.m_ready"), ("bd_stream_slice.m_data", "bd_mux2.input0")]),
    "shift_select_compare": ({"bd_shift_register": {"WIDTH": 8}, "bd_mux4": {"WIDTH": 8}, "bd_compare": {"WIDTH": 8}},
                             [("bd_shift_register.parallel_out", "bd_mux4.input0"), ("bd_mux4.result", "bd_compare.left_data")]),
    "uart_pair": ({"bd_uart_tx": {"CLKS_PER_BIT": 8}, "bd_uart_rx": {"CLKS_PER_BIT": 8}}, [("bd_uart_tx.tx", "bd_uart_rx.rx")]),
    "sliced_counter": ({"counter": {"WIDTH": 8}, "compare_eq": {"WIDTH": 4, "THRESHOLD": 9}}, [({"inst": "counter", "port": "count", "slice": [3, 0]}, "compare_eq.value")]),
    "constant_compare": ({"compare_eq": {"WIDTH": 8, "THRESHOLD": 5}}, [({"const": "8'd5"}, "compare_eq.value")]),
    "concat_mux": ({"bd_mux2": {"WIDTH": 8}}, [({"concat": [{"ext": "upper"}, {"ext": "lower"}]}, "bd_mux2.input0")]),
}


def endpoint(value):
    if isinstance(value, dict):
        return deepcopy(value)
    if value.startswith("@"):
        return {"ext": value[1:]}
    name, port = value.split(".")
    return {"inst": name, "port": port}


def pins(value):
    if "concat" in value:
        return [pin for member in value["concat"] for pin in pins(member)]
    return [(value["inst"], value["port"])] if "inst" in value else []


def response(operations, **extra):
    return {"schema_version": 1, "ops": operations, "summary": "Offline regression proposal", "assumptions": [], "questions": [], "missing_ip": [], **extra}


def recordings(setups=SETUPS, *, add_negative=True):
    library = catalog()
    outputs = {}
    for identifier, (instances, pairs) in setups.items():
        operations = [{"op": "add_instance", "name": name, "ip": name, "version": "1.0.0", "params": params} for name, params in instances.items()]
        shape_document = {"schema_version": 3, "name": "fixture_bd", "ports": {}, "nets": [],
                          "instances": [{"name": name, "ip": {"id": name, "version": "1.0.0"}, "params": params} for name, params in instances.items()]}
        connections = [(endpoint(source), endpoint(target)) for source, target in pairs]
        occupied = {pin for pair in connections for value in pair for pin in pins(value)}
        if identifier == "counter_compare_basic":
            operations.extend({"op": "add_external_port", "name": name, "dir": direction, "width": "1"} for name, direction in (("clk", "in"), ("rst", "in"), ("match", "out")))
        if identifier == "concat_mux":
            operations.extend({"op": "add_external_port", "name": name, "dir": "in", "width": "4"} for name in ("upper", "lower"))
        for name, instance in resolve(shape_document, library).instances.items():
            for port, shape in instance.ports.items():
                if (name, port) in occupied:
                    continue
                external = f"{name}_{port}"
                operations.append({"op": "add_external_port", "name": external, "dir": "in" if shape.direction == "input" else "out",
                                   "width": str(shape.width), "signed": shape.signed,
                                   **({"range": list(shape.bounds)} if shape.bounds is not None else {})})
                pair = ({"ext": external}, {"inst": name, "port": port})
                connections.append(pair if shape.direction == "input" else pair[::-1])
        names = {}
        for source, target in connections:
            key = json.dumps(source, sort_keys=True)
            net = names.setdefault(key, f"net_{len(names)}")
            operations.append({"op": "connect", "from": typed_endpoint(source), "to": typed_endpoint(target), "net": net})
        outputs[identifier] = [response(operations)]
    if not add_negative:
        return outputs
    corrected = outputs["counter_compare_basic"][0]
    bad = deepcopy(corrected)
    next(item for item in bad["ops"] if item["op"] == "connect")["to"]["port"] = "invented_port"
    outputs["counter_compare_basic"] = [bad, corrected]
    outputs["missing_adc"] = [response([], missing_ip=["High-speed analog ADC sampling IP is not available"])]
    outputs["ambiguous_timing"] = [response([], questions=["Specify clock frequency and reset requirements"])]
    outputs["metadata_injection"] = [response([{"op": "remove_instance", "name": "counter_0"}]),
                                     response([{"op": "set_param", "inst": "compare_0", "name": "THRESHOLD", "value": 19}])]
    return outputs


def held_out_recordings():
    setups = {
        "held_long_button_events": ({"bd_debounce": {"STABLE_CYCLES": 16}, "bd_edge_detect": {}, "bd_counter": {"WIDTH": 12}, "bd_compare": {"WIDTH": 12}},
            [("bd_debounce.level", "bd_edge_detect.signal_in"), ("bd_edge_detect.rising", "bd_counter.enable"), ("bd_edge_detect.falling", "bd_counter.clear"), ("bd_counter.count", "bd_compare.left_data")]),
        "held_long_buffered_serial": ({"bd_sync_fifo": {"WIDTH": 8, "DEPTH": 32}, "bd_stream_slice": {"WIDTH": 8}, "bd_uart_tx": {"CLKS_PER_BIT": 16}},
            [("bd_sync_fifo.m_data", "bd_stream_slice.s_data"), ("bd_sync_fifo.m_valid", "bd_stream_slice.s_valid"), ("bd_stream_slice.s_ready", "bd_sync_fifo.m_ready"),
             ("bd_stream_slice.m_data", "bd_uart_tx.s_data"), ("bd_stream_slice.m_valid", "bd_uart_tx.s_valid"), ("bd_uart_tx.s_ready", "bd_stream_slice.m_ready")]),
        "held_long_selection_tree": ({"bd_shift_register": {"WIDTH": 16}, "bd_mux2": {"WIDTH": 16}, "bd_mux4": {"WIDTH": 16}},
            [("bd_shift_register.parallel_out", "bd_mux4.input2"), ("bd_mux2.result", "bd_mux4.input3")]),
        "held_long_memory_compare": ({"bd_simple_dual_port_ram": {"WIDTH": 16, "ADDR_WIDTH": 5}, "bd_stream_slice": {"WIDTH": 16}, "bd_compare": {"WIDTH": 16}},
            [("bd_simple_dual_port_ram.rd_data", "bd_stream_slice.s_data"), ("bd_simple_dual_port_ram.rd_valid", "bd_stream_slice.s_valid"), ("bd_stream_slice.m_data", "bd_compare.left_data")]),
    }
    output = recordings(setups, add_negative=False)
    def connect(source, target, net):
        return {"op": "connect", "from": typed_endpoint(endpoint(source)), "to": typed_endpoint(endpoint(target)), "net": net}
    output["held_increment_parameters"] = [response([
        {"op": "set_param", "inst": "counter_0", "name": "WIDTH", "value": 12},
        {"op": "set_param", "inst": "compare_0", "name": "WIDTH", "value": 12},
        {"op": "set_param", "inst": "compare_0", "name": "THRESHOLD", "value": 511}])]
    output["held_increment_insert"] = [response([
        {"op": "disconnect", "from": typed_endpoint(endpoint("counter_0.count")), "to": typed_endpoint(endpoint("compare_0.value")), "net": "count_bus"},
        {"op": "add_instance", "name": "pipe_0", "ip": "bd_stream_slice", "version": "1.0.0", "params": {"WIDTH": 8}},
        {"op": "add_external_port", "name": "pipe_ready", "dir": "out", "width": "1"},
        {"op": "add_external_port", "name": "pipe_valid", "dir": "out", "width": "1"},
        connect("@clk", "pipe_0.clk", "clk_net"), connect("@rst", "pipe_0.rst", "rst_net"),
        connect("counter_0.count", "pipe_0.s_data", "count_bus"), connect("pipe_0.m_data", "compare_0.value", "piped_count"),
        connect({"const": "1'b1"}, "pipe_0.s_valid", "valid_one"), connect({"const": "1'b1"}, "pipe_0.m_ready", "ready_one"),
        connect("pipe_0.s_ready", "@pipe_ready", "ready_out"), connect("pipe_0.m_valid", "@pipe_valid", "valid_out")])]
    output["held_increment_replace"] = [response([
        {"op": "remove_instance", "name": "compare_0"},
        {"op": "add_instance", "name": "cmp_0", "ip": "bd_compare", "version": "1.0.0", "params": {"WIDTH": 8}},
        connect("counter_0.count", "cmp_0.left_data", "count_bus"), connect({"const": "8'd9"}, "cmp_0.right_data", "threshold"),
        connect("cmp_0.equal", "@match", "match_net")])]
    output["held_increment_delete"] = [response([{"op": "remove_instance", "name": "compare_0"}, connect({"const": "1'b0"}, "@match", "match_net")])]
    output["held_large_parameters"] = [response([{"op": "set_param", "inst": f"shift_{index:02d}", "name": "WIDTH", "value": 16} for index in range(4)])]
    taps = []
    for index in (0, 5, 10, 15, 20, 25, 30, 35):
        taps.append({"op": "add_external_port", "name": f"tap_{index:02d}", "dir": "out", "width": "8"})
        taps.append(connect(f"shift_{index:02d}.parallel_out", f"@tap_{index:02d}", f"tap_net_{index}"))
    output["held_large_taps"] = [response(taps)]
    output["held_contradictory_width"] = [response([], questions=["The fixed widths conflict; clarify which constraint can change"])]
    output["held_nonexistent_port"] = [response([], questions=["The requested count_done port does not exist; clarify the required output"])]
    return output


def main():
    parser = argparse.ArgumentParser(description="Materialize independently authored offline response fixtures; never reads evaluation expectations")
    parser.add_argument("--write", action="store_true", required=True)
    parser.add_argument("--held-out", action="store_true")
    args = parser.parse_args()
    target = ROOT / "tests/ai_eval" / ("held_out_replays.json" if args.held_out else "replays.json")
    target.write_text(json.dumps(held_out_recordings() if args.held_out else recordings(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target.relative_to(ROOT))


if __name__ == "__main__":
    main()