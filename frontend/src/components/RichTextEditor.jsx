import React from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import Underline from "@tiptap/extension-underline";
import Image from "@tiptap/extension-image";
import Placeholder from "@tiptap/extension-placeholder";
import { Table } from "@tiptap/extension-table";
import { TableRow } from "@tiptap/extension-table-row";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import {
  Bold, Italic, Underline as UnderlineIcon, Heading1, Heading2, List, ListOrdered,
  Link as LinkIcon, Image as ImageIcon, Table as TableIcon, Undo2, Redo2, Braces, RemoveFormatting,
} from "lucide-react";
import { Button } from "./ui/button";
import {
  Popover, PopoverContent, PopoverTrigger,
} from "./ui/popover";

/**
 * TipTap-based rich text editor with:
 *  - Bold / italic / underline / headings / lists / tables / images
 *  - Hyperlinks
 *  - Undo / redo
 *  - Merge-field variables (e.g. {{patient.first_name}}) inserted at the cursor
 *
 * Emits HTML via `onChange(html)`. Also emits a plain-text fallback via
 * `onPlainTextChange(text)` for SMS previews.
 */
const DEFAULT_VARIABLES = [
  { group: "Patient", items: [
    { key: "patient.first_name", label: "First name" },
    { key: "patient.last_name", label: "Last name" },
    { key: "patient.full_name", label: "Full name" },
    { key: "patient.email", label: "Email" },
    { key: "patient.phone", label: "Phone" },
  ]},
  { group: "Appointment", items: [
    { key: "appointment.date", label: "Date" },
    { key: "appointment.time", label: "Time" },
    { key: "appointment.provider", label: "Provider" },
  ]},
  { group: "Provider", items: [
    { key: "provider.name", label: "Provider name" },
  ]},
  { group: "Membership / Package", items: [
    { key: "membership.name", label: "Membership name" },
    { key: "package.name", label: "Package name" },
  ]},
  { group: "Clinic", items: [
    { key: "clinic.name", label: "Clinic name" },
    { key: "clinic.phone", label: "Clinic phone" },
    { key: "clinic.email", label: "Clinic email" },
  ]},
];

export default function RichTextEditor({
  value = "",
  onChange,
  onPlainTextChange,
  placeholder = "Compose your message…",
  variables = DEFAULT_VARIABLES,
  minHeight = 220,
  testid = "rich-text-editor",
}) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Underline,
      Link.configure({ openOnClick: false, autolink: true, HTMLAttributes: { rel: "noopener noreferrer" } }),
      Image,
      Placeholder.configure({ placeholder }),
      Table.configure({ resizable: false }),
      TableRow, TableCell, TableHeader,
    ],
    content: value || "",
    onUpdate: ({ editor: ed }) => {
      const html = ed.getHTML();
      onChange?.(html);
      onPlainTextChange?.(ed.getText());
    },
  });

  // Keep external value in sync (only when it visibly differs to avoid caret jumps).
  React.useEffect(() => {
    if (!editor) return;
    if ((value || "") !== editor.getHTML()) {
      editor.commands.setContent(value || "", false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  if (!editor) return null;

  const insertVariable = (key) => {
    editor.chain().focus().insertContent(`{{${key}}}`).run();
  };

  const addLink = () => {
    const url = window.prompt("Enter URL", editor.getAttributes("link").href || "https://");
    if (url === null) return;
    if (url === "") { editor.chain().focus().unsetLink().run(); return; }
    editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
  };

  const addImage = () => {
    const url = window.prompt("Image URL (must be https)");
    if (!url) return;
    editor.chain().focus().setImage({ src: url }).run();
  };

  return (
    <div
      className="rounded-xl border border-[#d9e2db] bg-white overflow-hidden"
      data-testid={testid}
    >
      <div className="flex flex-wrap items-center gap-1 border-b border-[#e2ebe4] px-2 py-1.5 bg-[#f7fbf8]">
        <Btn onClick={() => editor.chain().focus().toggleBold().run()} active={editor.isActive("bold")} label="Bold" testid={`${testid}-bold`}><Bold size={14} /></Btn>
        <Btn onClick={() => editor.chain().focus().toggleItalic().run()} active={editor.isActive("italic")} label="Italic" testid={`${testid}-italic`}><Italic size={14} /></Btn>
        <Btn onClick={() => editor.chain().focus().toggleUnderline().run()} active={editor.isActive("underline")} label="Underline" testid={`${testid}-underline`}><UnderlineIcon size={14} /></Btn>
        <Divider />
        <Btn onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} active={editor.isActive("heading", { level: 1 })} label="H1"><Heading1 size={14} /></Btn>
        <Btn onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} active={editor.isActive("heading", { level: 2 })} label="H2"><Heading2 size={14} /></Btn>
        <Divider />
        <Btn onClick={() => editor.chain().focus().toggleBulletList().run()} active={editor.isActive("bulletList")} label="Bullets"><List size={14} /></Btn>
        <Btn onClick={() => editor.chain().focus().toggleOrderedList().run()} active={editor.isActive("orderedList")} label="Numbered"><ListOrdered size={14} /></Btn>
        <Divider />
        <Btn onClick={addLink} active={editor.isActive("link")} label="Link"><LinkIcon size={14} /></Btn>
        <Btn onClick={addImage} label="Image"><ImageIcon size={14} /></Btn>
        <Btn onClick={() => editor.chain().focus().insertTable({ rows: 2, cols: 3, withHeaderRow: true }).run()} label="Table"><TableIcon size={14} /></Btn>
        <Divider />
        <Popover>
          <PopoverTrigger asChild>
            <Button
              type="button" variant="ghost" size="sm"
              className="h-7 px-2 rounded-md text-[#3d6b52] hover:bg-[#eaf2ec]"
              data-testid={`${testid}-vars`}
            >
              <Braces size={13} className="mr-1" /> Variables
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-64 p-2 bg-white border border-[#d9e2db]">
            <div className="text-[10px] uppercase tracking-widest text-[#8a6a3c] px-1 pb-2">Merge fields</div>
            <div className="max-h-72 overflow-y-auto space-y-3">
              {variables.map((g) => (
                <div key={g.group}>
                  <div className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mb-1 px-1">{g.group}</div>
                  <div className="space-y-0.5">
                    {g.items.map((v) => (
                      <button
                        key={v.key}
                        type="button"
                        onClick={() => insertVariable(v.key)}
                        className="w-full text-left px-2 py-1 rounded text-xs hover:bg-[#eaf2ec] text-[#1f2a22] flex items-center justify-between"
                        data-testid={`${testid}-var-${v.key}`}
                      >
                        <span className="font-medium">{v.label}</span>
                        <span className="text-[10px] text-slate-500 font-mono">{`{{${v.key}}}`}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </PopoverContent>
        </Popover>
        <Divider />
        <Btn onClick={() => editor.chain().focus().undo().run()} label="Undo"><Undo2 size={14} /></Btn>
        <Btn onClick={() => editor.chain().focus().redo().run()} label="Redo"><Redo2 size={14} /></Btn>
        <Btn onClick={() => editor.chain().focus().unsetAllMarks().clearNodes().run()} label="Clear"><RemoveFormatting size={14} /></Btn>
      </div>
      <EditorContent
        editor={editor}
        className="tiptap-content prose prose-sm max-w-none px-3 py-2 focus:outline-none"
        style={{ minHeight }}
      />
    </div>
  );
}

function Btn({ children, onClick, active, label, testid }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      data-testid={testid}
      className={`h-7 w-7 flex items-center justify-center rounded-md transition ${
        active ? "bg-[#2f6a4a] text-white" : "text-[#3d6b52] hover:bg-[#eaf2ec]"
      }`}
    >
      {children}
    </button>
  );
}

function Divider() {
  return <div className="w-px h-4 bg-[#d9e2db] mx-0.5" />;
}

/** Client-side merge-field substitution for preview / plain text SMS. */
export function fillVariables(text, ctx = {}) {
  return String(text || "").replace(/\{\{\s*([\w.]+)\s*\}\}/g, (_m, key) => {
    const parts = key.split(".");
    let cur = ctx;
    for (const p of parts) { cur = cur?.[p]; if (cur == null) return _m; }
    return String(cur);
  });
}
