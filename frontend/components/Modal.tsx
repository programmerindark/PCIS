"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

export default function Modal({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  // Rendered into <body>, NOT in place.
  //
  // `.page` carries z-index: 1 and `.appbar` is its SIBLING at z-index: 30,
  // so a modal rendered inside .page is trapped in that stacking context --
  // its own z-index: 100 is compared only against other children of .page,
  // and the whole subtree still paints below the appbar. The result was the
  // sticky header sitting on top of an opened chart, hiding its title and
  // the first inch of the graph.
  //
  // A portal puts the overlay outside .page entirely, where z-index: 100
  // means what it says. Mounted-check because document does not exist
  // during server rendering.
  if (!mounted) return null;

  return createPortal(
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="modal-title">{title}</div>
            {subtitle && <div className="muted" style={{ fontSize: 13, marginTop: 3 }}>{subtitle}</div>}
          </div>
          <button className="close-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {children}
      </div>
    </div>,
    document.body
  );
}
