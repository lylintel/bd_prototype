import { Compartment, EditorState, Facet, Text } from "@codemirror/state";
import { EditorView, drawSelection, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { StreamLanguage, bracketMatching, defaultHighlightStyle, foldGutter, syntaxHighlighting } from "@codemirror/language";
import { json } from "@codemirror/lang-json";
import { verilog } from "@codemirror/legacy-modes/mode/verilog";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import { t } from "../i18n.js";

export const largeDocument = Facet.define({ combine: (values) => values[0] ?? false });

const theme = EditorView.theme({
  "&": { height: "100%", color: "#3f5968", backgroundColor: "#fff" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { overflow: "auto", fontFamily: "IBM Plex Mono, monospace", fontSize: "var(--code-font-size, 12px)", lineHeight: "1.6" },
  ".cm-content": { padding: "8px 0", caretColor: "#008875" },
  ".cm-gutters": { minWidth: "44px", backgroundColor: "#f5f8fa", color: "#8799a5", borderRight: "1px solid #e1e7eb" },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "#edf7f4" },
});

function extras(large) {
  return [largeDocument.of(large), ...(large ? [] : [highlightActiveLine(), highlightActiveLineGutter(), bracketMatching(), foldGutter(), highlightSelectionMatches()])];
}

export function createOutputState(value, { language = "verilog", readOnly = true, label = "", onChange = undefined } = {}) {
  const doc = Text.of(value.split(/\r\n?|\n/));
  const profile = new Compartment();
  const phrases = { Find: "find", Replace: "replace", next: "next", previous: "previous", all: "all", "match case": "matchCase",
    regexp: "regexp", "by word": "wholeWord", replace: "replace", "replace all": "replaceAll", close: "close", "Go to line": "goToLine", go: "go",
    "current match": "currentMatch", "on line": "onLine", "replaced match on line $": "replacedLine", "replaced $ matches": "replacedCount",
    "Folded lines": "foldedLines", "Unfolded lines": "unfoldedLines", to: "to", "folded code": "foldedCode", unfold: "unfold", "Fold line": "foldLine", "Unfold line": "unfoldLine" };
  return EditorState.create({ doc, extensions: [
    theme, lineNumbers(), drawSelection(), syntaxHighlighting(defaultHighlightStyle),
    language === "json" ? json() : StreamLanguage.define(verilog),
    EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly), EditorState.tabSize.of(2),
    EditorView.contentAttributes.of({ "aria-label": label, "aria-readonly": String(readOnly), tabindex: "0", spellcheck: "false" }),
    EditorView.editorAttributes.compute([largeDocument, "doc"], (state) => ({ "data-large-document": String(state.facet(largeDocument)), "data-line-count": String(state.doc.lines) })),
    EditorState.phrases.of(Object.fromEntries(Object.entries(phrases).map(([phrase, key]) => [phrase, t(`output.${key}`)]))),
    keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap, indentWithTab]), ...(readOnly ? [] : [history()]),
    profile.of(extras(doc.lines > 5000)),
    EditorState.transactionExtender.of((transaction) => transaction.docChanged && (transaction.startState.doc.lines > 5000) !== (transaction.newDoc.lines > 5000)
      ? { effects: profile.reconfigure(extras(transaction.newDoc.lines > 5000)) } : null),
    EditorView.updateListener.of((update) => { if (update.docChanged) onChange?.(update.state.doc.toString()); }),
  ] });
}