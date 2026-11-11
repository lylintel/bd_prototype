import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, Check, Cpu, FolderOpen, LoaderCircle, Plus, RefreshCw, Upload, X } from "lucide-react";
import { t, hasMessage } from "../i18n.js";
import { IP_DRAG_TYPE, droppedFiles, encodeUpload, matchesLibrary, readImportEvents } from "./model.js";
import "./library.css";

export function OriginBadge({ origin }) {
  const kind = ["builtin", "imported", "manual"].includes(origin) ? origin : "manual";
  return <small className={`ip-origin ip-origin-${kind}`}>{t(`ip.origin.${kind}`)}</small>;
}

export function LibraryList({ baseDir, revision, search, onCatalogChange, onAdd }) {
  const [rows, setRows] = useState([]);
  const [loadedBase, setLoadedBase] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setRows([]);
    setLoadedBase("");
    onCatalogChange({ baseDir, entries: [] });
    fetch(`/api/ip/library?base_dir=${encodeURIComponent(baseDir)}`, { signal: controller.signal })
      .then(async (response) => {
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || t("ip.httpError", { status: response.status }));
        if (!Array.isArray(body.entries)) throw new Error(t("ip.streamInvalid"));
        if (controller.signal.aborted) return;
        setRows(body.entries);
        setLoadedBase(baseDir);
        onCatalogChange({ baseDir, entries: body.entries });
      }).catch((failure) => { if (failure.name !== "AbortError") setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [baseDir, revision, reload, onCatalogChange]);
  const filtered = rows.filter((row) => matchesLibrary(row, search));
  return <section className="ip-library" aria-label={t("ip.library")}>
    <div className="library-section-title"><span>{t("ip.library")}</span><span>{filtered.length}</span>
      <button type="button" className="icon-button" title={t("common.retry")} aria-label={t("ip.refresh")} onClick={() => setReload(reload + 1)}><RefreshCw size={13} /></button>
    </div>
    {loading ? <div className="ip-library-state" role="status"><LoaderCircle size={14} className="spin" />{t("common.loading")}</div>
      : error ? <div className="ip-library-state error" role="alert">{error}</div>
      : <div className="ip-library-scroll" role="list">
        {filtered.map((row) => <div key={`${row.metadata.id}@${row.metadata.version}`} className="module-item ip-library-item" role="listitem"
          data-testid={`ip-row-${row.metadata.id}@${row.metadata.version}`} draggable={row.usable} tabIndex={row.usable ? 0 : -1} aria-disabled={!row.usable}
          onDragStart={(event) => { event.dataTransfer.setData(IP_DRAG_TYPE, JSON.stringify({ id: row.metadata.id, version: row.metadata.version })); event.dataTransfer.effectAllowed = "copy"; }}
          onDoubleClick={() => { if (row.usable) onAdd(row, undefined, loadedBase); }}
          onKeyDown={(event) => { if (event.key === "Enter" && event.target === event.currentTarget && row.usable) onAdd(row, undefined, loadedBase); }}>
          <div className="module-icon"><Cpu size={18} /></div>
          <div className="module-label"><strong title={row.metadata.id}>{row.metadata.display_name}</strong>
            <span>{t("ip.versionPorts", { version: row.metadata.version, count: row.metadata.ports.length })}</span><OriginBadge origin={row.origin} />
            {!row.usable && <span className="ip-unavailable" title={row.diagnostics?.map((item) => item.message).join("\n")}>{t("ip.unavailable")}</span>}
          </div>
          <button type="button" className="icon-button" title={t("ip.add", { name: row.metadata.id })} aria-label={t("ip.add", { name: row.metadata.id })}
            disabled={!row.usable || loadedBase !== baseDir} onClick={() => onAdd(row, undefined, loadedBase)}><Plus size={14} /></button>
        </div>)}
        {!filtered.length && <div className="ip-library-state">{t("ip.empty")}</div>}
      </div>}
  </section>;
}

function MetadataEditor({ record, disabled, onChange }) {
  const metadata = record.metadata;
  const update = (change) => onChange(record.key, change);
  return <fieldset className="ip-editor" disabled={disabled || !record.selected}>
    <div className="ip-editor-heading"><code>{metadata.id}</code><OriginBadge origin="imported" /></div>
    <div className="ip-fields">
      <label>{t("ip.displayName")}<input aria-label={t("ip.displayName")} value={metadata.display_name} maxLength={256} onChange={(event) => update((next) => { next.display_name = event.target.value; })} /></label>
      <label>{t("ip.version")}<input aria-label={t("ip.version")} value={metadata.version} maxLength={64} onChange={(event) => update((next) => { next.version = event.target.value; })} /></label>
      <label className="ip-field-wide">{t("ip.tags")}<input aria-label={t("ip.tags")} value={metadata.tags.join(", ")} onChange={(event) => update((next) => { next.tags = event.target.value.split(",").map((value) => value.trim()).filter(Boolean); })} /></label>
      <label className="ip-field-wide">{t("ip.description")}<textarea aria-label={t("ip.description")} value={metadata.description} maxLength={65536} rows={2} onChange={(event) => update((next) => { next.description = event.target.value; })} /></label>
    </div>
    <h3>{t("ip.parameters")}</h3>
    {metadata.parameters.map((parameter, index) => <label className="ip-parameter" key={index}><code>{parameter.name}</code>
      <input aria-label={t("ip.parameterValue", { name: parameter.name })} value={parameter.default} maxLength={4096}
        onChange={(event) => update((next) => { next.parameters[index].default = event.target.value; })} /></label>)}
    {!metadata.parameters.length && <div className="ip-muted">{t("ip.noParameters")}</div>}
    <h3>{t("ip.ports")}</h3>
    {metadata.ports.map((port, index) => <div className="ip-port-editor" key={index}>
      <div className="ip-port-fields">
        <label>{t("ip.portName")}<input aria-label={t("ip.portNameAt", { index: index + 1 })} value={port.name} onChange={(event) => update((next) => { next.ports[index].name = event.target.value; })} /></label>
        <label>{t("ip.direction")}<select aria-label={t("ip.directionFor", { name: port.name })} value={port.dir} onChange={(event) => update((next) => { next.ports[index].dir = event.target.value; })}>
          {["in", "out", "inout"].map((direction) => <option key={direction} value={direction}>{t(`ip.direction.${direction}`)}</option>)}</select></label>
        <label>{t("ip.width")}<input aria-label={t("ip.widthFor", { name: port.name })} value={port.width} maxLength={4096} onChange={(event) => update((next) => { next.ports[index].width = event.target.value; })} /></label>
      </div>
      <div className="ip-role-fields">
        <label>{t("ip.role")}<select aria-label={t("ip.roleFor", { name: port.name })} value={port.role?.kind ?? "none"}
          onChange={(event) => update((next) => {
            const kind = event.target.value;
            if (kind === "none") delete next.ports[index].role;
            else next.ports[index].role = { kind, confidence: 1, confirmed: false, ...(kind === "reset" ? { polarity: "unknown", async: "unknown" } : {}) };
          })}>{["none", "clock", "reset", "data", "control", "unknown"].map((kind) => <option key={kind} value={kind}>{t(`ip.role.${kind}`)}</option>)}</select></label>
        {port.role && <>
          <label className="ip-check"><input type="checkbox" checked={port.role.confirmed} aria-label={t("ip.confirmRoleFor", { name: port.name })}
            onChange={(event) => update((next) => { next.ports[index].role.confirmed = event.target.checked; })} />{t("ip.confirmRole")}</label>
          <span className="ip-muted">{t("ip.confidence", { value: Math.round(port.role.confidence * 100) })}</span>
        </>}
        {port.role?.kind === "reset" && <>
          <label>{t("ip.polarity")}<select aria-label={t("ip.polarityFor", { name: port.name })} value={port.role.polarity}
            onChange={(event) => update((next) => { next.ports[index].role.polarity = event.target.value; next.ports[index].role.confirmed = false; })}>
            {["unknown", "high", "low"].map((polarity) => <option key={polarity} value={polarity}>{t(`ip.polarity.${polarity}`)}</option>)}</select></label>
          <label>{t("ip.timing")}<select aria-label={t("ip.timingFor", { name: port.name })} value={String(port.role.async)}
            onChange={(event) => update((next) => { next.ports[index].role.async = event.target.value === "unknown" ? "unknown" : event.target.value === "true"; next.ports[index].role.confirmed = false; })}>
            {["unknown", "false", "true"].map((timing) => <option key={timing} value={timing}>{t(`ip.timing.${timing}`)}</option>)}</select></label>
        </>}
      </div>
    </div>)}
  </fieldset>;
}

export function ImportButton({ token, onComplete, onOpenChange, onNotify }) {
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState([]);
  const [active, setActive] = useState(null);
  const [busy, setBusy] = useState("");
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [license, setLicense] = useState("NOASSERTION");
  const dialog = useRef(null);
  const chooser = useRef(null);
  const folderChooser = useRef(null);
  const abort = useRef(null);
  const selectionSerial = useRef(0);
  useEffect(() => {
    onOpenChange(open);
    if (open && !dialog.current.open) dialog.current.showModal();
    if (!open && dialog.current.open) dialog.current.close();
  }, [open, onOpenChange]);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => { folderChooser.current?.setAttribute("webkitdirectory", ""); }, []);
  const records = groups.flatMap((group) => group.records);
  const selected = records.filter((record) => record.selected);
  const current = records.find((record) => record.key === active) ?? records[0];

  function resetDialog() {
    selectionSerial.current++;
    setOpen(false); setGroups([]); setActive(null); setError(""); setBusy(""); setProgress("");
  }
  function closeDialog() {
    if (busy === "commit") return;
    abort.current?.abort(); abort.current = null; resetDialog();
  }
  function updateRecord(key, change) {
    setGroups((previous) => previous.map((group) => ({ ...group, records: group.records.map((record) => record.key === key ? change(record) : record) })));
  }
  function updateMetadata(key, change) {
    updateRecord(key, (record) => { const metadata = structuredClone(record.metadata); change(metadata); return { ...record, metadata }; });
  }
  async function send(payload, signal, onEvent) {
    const response = await fetch("/api/ip/import", { method: "POST", headers: { "Content-Type": "application/json", "X-BD-Token": token }, body: JSON.stringify(payload), signal });
    await readImportEvents(response, onEvent);
  }
  async function preview(files) {
    if (busy || !files.length) return;
    if (files.length + groups.length > 200) { setError(t("ip.tooManyFiles")); return; }
    const controller = new AbortController();
    abort.current = controller;
    setBusy("preview"); setError("");
    try {
      for (const [index, file] of files.entries()) {
        if (controller.signal.aborted) break;
        setProgress(t("ip.parsing", { name: file.name }));
        const key = `${groups.length + index}:${file.name}`;
        setGroups((previous) => [...previous, { key, upload: { name: file.name }, records: [], errors: [] }]);
        try {
          const upload = await encodeUpload(file);
          setGroups((previous) => previous.map((group) => group.key === key ? { ...group, upload } : group));
          await send({ action: "preview", files: [upload], license }, controller.signal, (event) => {
          if (controller.signal.aborted || event.type !== "ip") return;
          if (event.metadata) {
            const record = { ...event, key: `${key}:${event.id}`, selected: event.status !== "skipped" };
            setGroups((previous) => previous.map((group) => group.key === key ? { ...group, records: [...group.records, record] } : group));
            setActive((previous) => previous ?? record.key);
          } else {
            const messages = event.diagnostics?.map((item) => item.message) ?? [t("ip.invalidFile")];
            setGroups((previous) => previous.map((group) => group.key === key ? { ...group, errors: [...group.errors, ...messages] } : group));
          }
          });
        } catch (failure) {
          if (failure.name === "AbortError") break;
          setGroups((previous) => previous.map((group) => group.key === key ? { ...group, errors: [...group.errors, failure.message] } : group));
        }
      }
    } catch (failure) { if (failure.name !== "AbortError") setError(failure.message); }
    finally { if (abort.current === controller) { setBusy(""); setProgress(""); } }
  }
  async function commit() {
    if (busy || !selected.length) return;
    const controller = new AbortController();
    abort.current = controller;
    setBusy("commit"); setError("");
    let imported = 0, skipped = 0, failed = groups.some((group) => group.errors.length);
    try {
      for (const group of groups) {
        const chosen = group.records.filter((record) => record.selected);
        if (!chosen.length) continue;
        setProgress(t("ip.committing", { name: group.upload.name }));
        const metadata = Object.fromEntries(chosen.map((record) => [record.id, record.metadata]));
        await send({ action: "commit", files: [group.upload], metadata, license }, controller.signal, (event) => {
          if (event.type !== "ip") return;
          if (event.status === "imported") imported++;
          if (event.status === "skipped") skipped++;
          if (["invalid", "needs_version"].includes(event.status)) failed = true;
          const key = `${group.key}:${event.id}`;
          updateRecord(key, (record) => ({ ...record, ...event, key, selected: ["invalid", "needs_version"].includes(event.status) }));
          if (!event.id) setError(event.diagnostics?.map((item) => item.message).join("\n") || t("ip.invalidFile"));
        });
      }
      onComplete();
      if (!failed) { onNotify(t("ip.completed", { imported, skipped })); resetDialog(); }
    } catch (failure) { if (failure.name !== "AbortError") setError(failure.message); onComplete(); }
    finally { if (abort.current === controller) { setBusy(""); setProgress(""); } }
  }
  function changeLicense(value) {
    setLicense(value);
    setGroups((previous) => previous.map((group) => ({ ...group, records: group.records.map((record) => ({ ...record, metadata: { ...record.metadata, source: { ...record.metadata.source, license: value } } })) })));
  }
  async function dropFiles(event) {
    event.preventDefault(); event.stopPropagation();
    if (busy) return;
    const serial = selectionSerial.current;
    try {
      const files = await droppedFiles(event.dataTransfer);
      if (selectionSerial.current === serial && dialog.current.open) await preview(files);
    } catch (failure) { if (selectionSerial.current === serial) setError(failure.message); }
  }
  return <>
    <button type="button" className="icon-button ip-import-trigger" title={t("ip.import")} aria-label={t("ip.import")} disabled={!token} onClick={() => setOpen(true)}><Upload size={16} /></button>
    {createPortal(<dialog ref={dialog} className="ip-dialog" aria-labelledby="ip-import-title" onCancel={(event) => { event.preventDefault(); closeDialog(); }}
      onDragOver={(event) => event.preventDefault()} onDrop={dropFiles}>
      <div className="dialog-heading"><h2 id="ip-import-title">{t("ip.importTitle")}</h2><button type="button" className="icon-button" title={t("common.close")} aria-label={t("common.close")} disabled={busy === "commit"} onClick={closeDialog}><X size={17} /></button></div>
      <div className="ip-import-toolbar">
        <input ref={chooser} type="file" accept=".v,.sv" multiple hidden aria-label={t("ip.files")} onChange={(event) => { const files = Array.from(event.target.files ?? []); event.target.value = ""; preview(files); }} />
        <input ref={folderChooser} type="file" multiple hidden aria-label={t("ip.folder")} onChange={(event) => { const files = Array.from(event.target.files ?? []).filter((file) => /\.(v|sv)$/i.test(file.name)); event.target.value = ""; preview(files); }} />
        <button type="button" className="button secondary" disabled={Boolean(busy)} onClick={() => chooser.current.click()}><Upload size={15} />{t("ip.chooseFiles")}</button>
        <button type="button" className="button secondary" disabled={Boolean(busy)} onClick={() => folderChooser.current.click()}><FolderOpen size={15} />{t("ip.chooseFolder")}</button>
        <label>{t("ip.license")}<input aria-label={t("ip.license")} value={license} maxLength={256} disabled={Boolean(busy)} onChange={(event) => changeLicense(event.target.value)} /></label>
        <span className="ip-muted">{t("ip.fileCount", { count: groups.length })}</span>
      </div>
      {busy && <div className="ip-progress" role="status"><LoaderCircle size={15} className="spin" />{progress || t("common.loading")}</div>}
      <div className="ip-errors">
        {error && <div className="ip-import-error" role="alert"><AlertCircle size={16} /><span>{error}</span></div>}
        {groups.flatMap((group) => group.errors.map((message, index) => <div className="ip-import-error" role="alert" key={`${group.key}:${index}`}><code>{group.upload.name}</code><span>{message}</span></div>))}
      </div>
      <div className="ip-import-body">
        <div className="ip-candidates">
          <label className="ip-check ip-select-all"><input type="checkbox" aria-label={t("ip.selectAll")} checked={Boolean(records.length) && selected.length === records.length} disabled={Boolean(busy)}
            onChange={(event) => setGroups((previous) => previous.map((group) => ({ ...group, records: group.records.map((record) => ({ ...record, selected: event.target.checked && record.status !== "imported" })) })))} />{t("ip.selectAll")}</label>
          {records.map((record) => <div className={`ip-candidate ${current?.key === record.key ? "active" : ""}`} key={record.key}>
            <input type="checkbox" aria-label={t("ip.selectModule", { name: record.id })} checked={record.selected} disabled={Boolean(busy) || record.status === "imported"} onChange={(event) => updateRecord(record.key, (value) => ({ ...value, selected: event.target.checked }))} />
            <button type="button" aria-label={t("ip.inspectModule", { name: record.id })} onClick={() => setActive(record.key)}><code>{record.id}</code><span className={`ip-status ip-status-${record.status}`}>{t(hasMessage(`ip.status.${record.status}`) ? `ip.status.${record.status}` : "ip.status.unknown")}</span></button>
          </div>)}
          {!records.length && <div className="ip-library-state">{t("ip.noFiles")}</div>}
        </div>
        <div className="ip-detail">
          {current && <>
            {current.diagnostics?.map((item, index) => <div className="ip-import-error" role="alert" key={index}>{item.message}</div>)}
            {current.status === "needs_version" && <div className="ip-version-diff" role="status"><strong>{t("ip.status.needs_version")}</strong>
              {Object.entries(current.diff ?? {}).filter(([, values]) => Array.isArray(values) && values.length).map(([kind, values]) => <div key={kind}><span>{t(`ip.diff.${kind}`)}</span><code>{values.join(", ")}</code></div>)}
            </div>}
            <MetadataEditor record={current} disabled={Boolean(busy)} onChange={updateMetadata} />
          </>}
        </div>
      </div>
      <div className="dialog-actions"><button type="button" className="button secondary" disabled={busy === "commit"} onClick={closeDialog}>{t("common.cancel")}</button>
        <button type="button" className="button primary" disabled={Boolean(busy) || !selected.length} onClick={commit}><Check size={15} />{t("ip.confirmImport", { count: selected.length })}</button></div>
    </dialog>, document.body)}
  </>;
}