import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Rnd } from "react-rnd";
import { GripHorizontal, Maximize2, Minimize2, Move, PanelBottom, PanelsTopLeft, ZoomIn, ZoomOut } from "lucide-react";

const HEADER_HEIGHT = 70;

function fitRect(rect, viewport) {
  const width = Math.min(Math.max(rect.width, 320), viewport.width - 16);
  const height = Math.min(Math.max(rect.height, 180), viewport.height - 16);
  return { width, height, x: Math.max(8, Math.min(rect.x, viewport.width - width - 8)), y: Math.max(8, Math.min(rect.y, viewport.height - height - 8)) };
}

function Tool({ icon: Icon, label, ...props }) {
  return <button type="button" className="icon-button" aria-label={label} title={label} {...props}><Icon size={15} strokeWidth={1.7} /></button>;
}

export default function OutputWindow({ open, onOpenChange, tab, tabs, children }) {
  const [viewport, setViewport] = useState(() => ({ width: window.innerWidth, height: window.innerHeight }));
  const [mode, setMode] = useState("docked");
  const [restoreMode, setRestoreMode] = useState("docked");
  const [dockHeight, setDockHeight] = useState(260);
  const [rect, setRect] = useState(() => fitRect({ width: 840, height: 490, x: 250, y: 180 }, { width: window.innerWidth, height: window.innerHeight }));
  const [fontSize, setFontSize] = useState(12);
  const frame = useRef(null);
  const dock = useRef(null);
  const maximumDockHeight = Math.max(150, viewport.height - 380);
  const height = open ? Math.min(dockHeight, maximumDockHeight) : HEADER_HEIGHT;

  useEffect(() => {
    const resize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  useEffect(() => { setRect((previous) => fitRect(previous, viewport)); }, [viewport]);

  function toggleFloat() {
    if (mode === "docked") {
      const bounds = dock.current?.getBoundingClientRect();
      setRect(fitRect({ ...rect, x: bounds?.left ?? rect.x, y: bounds?.top ?? rect.y }, viewport));
      setMode("floating");
    } else setMode("docked");
    onOpenChange(true);
  }

  function toggleMaximize() {
    if (mode === "maximized") setMode(restoreMode);
    else { setRestoreMode(mode); setMode("maximized"); }
    onOpenChange(true);
  }

  function moveWithKeyboard(event) {
    if (mode !== "floating") return;
    const delta = { ArrowLeft: [-20, 0], ArrowRight: [20, 0], ArrowUp: [0, -20], ArrowDown: [0, 20] }[event.key];
    if (!delta) return;
    event.preventDefault();
    setRect(fitRect({ ...rect, x: rect.x + delta[0], y: rect.y + delta[1] }, viewport));
  }

  const maximized = mode === "maximized";
  const floating = mode !== "docked";
  const size = maximized ? { width: viewport.width - 16, height: viewport.height - 16 } : floating ? { width: rect.width, height: rect.height } : { width: "100%", height };
  const position = maximized ? { x: 8, y: 8 } : floating ? { x: rect.x, y: rect.y } : { x: 0, y: 0 };
  const panel = <Rnd ref={frame} className={`output-panel output-window ${mode} ${open ? "" : "collapsed"}`} size={size} position={position}
    minWidth={floating ? Math.min(320, viewport.width - 16) : undefined} minHeight={open ? floating ? 180 : 150 : HEADER_HEIGHT}
    maxWidth={floating ? viewport.width - 16 : undefined} maxHeight={floating ? viewport.height - 16 : maximumDockHeight}
    bounds={floating ? "window" : undefined} disableDragging={mode !== "floating"} dragHandleClassName="output-window-titlebar"
    cancel="button, input, textarea, select" enableResizing={open && !maximized ? floating ? true : { top: true } : false}
    resizeHandleStyles={{ top: { height: 8, top: -4 }, bottomRight: { width: 18, height: 18, bottom: 0, right: 0, zIndex: 4 } }}
    resizeHandleComponent={{ top: !floating ? <div className="output-height-handle" role="separator" aria-label="调整代码窗口高度" aria-orientation="horizontal" tabIndex={0}
      aria-valuemin={150} aria-valuemax={maximumDockHeight} aria-valuenow={height}
      onKeyDown={(event) => { if (["ArrowUp", "ArrowDown"].includes(event.key)) { event.preventDefault(); setDockHeight(Math.max(150, Math.min(maximumDockHeight, height + (event.key === "ArrowUp" ? 20 : -20)))); } }} /> : undefined,
      bottomRight: floating ? <span className="output-corner-handle" aria-label="调整浮动代码窗口大小"><GripHorizontal size={13} /></span> : undefined }}
    onDragStop={(_, data) => setRect(fitRect({ ...rect, x: data.x, y: data.y }, viewport))}
    onResizeStop={(_, __, element, ___, nextPosition) => {
      if (floating) setRect(fitRect({ width: element.offsetWidth, height: element.offsetHeight, ...nextPosition }, viewport));
      else { setDockHeight(element.offsetHeight); frame.current?.updatePosition({ x: 0, y: 0 }); }
    }}
    style={{ display: "flex", flexDirection: "column", position: "absolute", "--code-font-size": `${fontSize}px` }}>
    <div className="output-window-titlebar" onDoubleClick={(event) => { if (event.target instanceof Element && !event.target.closest("button")) toggleMaximize(); }}>
      <div className="output-window-title" tabIndex={mode === "floating" ? 0 : undefined} aria-label="移动代码窗口" title={mode === "floating" ? "拖动代码窗口" : "输出"} onKeyDown={moveWithKeyboard}>
        {floating ? <Move size={13} /> : <GripHorizontal size={14} />}<span>输出</span>
      </div>
      <div className="output-window-actions">
        <Tool icon={ZoomOut} label="缩小代码字号" disabled={tab === "diagnostics" || fontSize <= 10} onClick={() => setFontSize(fontSize - 1)} />
        <span className="code-font-size">{fontSize}px</span>
        <Tool icon={ZoomIn} label="放大代码字号" disabled={tab === "diagnostics" || fontSize >= 24} onClick={() => setFontSize(fontSize + 1)} />
        <span className="toolbar-divider" />
        <Tool icon={mode === "docked" ? PanelsTopLeft : PanelBottom} label={mode === "docked" ? "浮动代码窗口" : "固定代码窗口到底部"} onClick={toggleFloat} />
        <Tool icon={maximized ? Minimize2 : Maximize2} label={maximized ? "还原代码窗口" : "最大化代码窗口"} onClick={toggleMaximize} />
        <Tool icon={PanelBottom} label={open ? "收起输出面板" : "展开输出面板"} onClick={() => { setMode("docked"); onOpenChange(!open); }} />
      </div>
    </div>
    <div className="output-tabs" role="tablist">{tabs}</div>
    {open && children}
  </Rnd>;

  return floating ? createPortal(panel, document.body) : <div className="output-dock" ref={dock} style={{ height }}>{panel}</div>;
}