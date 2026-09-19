import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Archive, ArchiveRestore, Pencil, Pin, PinOff, Trash2 } from "lucide-react";

import type { TopicSummary } from "../protocol/messages";

export interface MenuPosition {
  left: number;
  top: number;
  placement: "above" | "below";
}

export type TopicMenuActionId = "rename" | "pin" | "unpin" | "archive" | "unarchive" | "delete";

interface TopicOverflowMenuProps {
  topic: TopicSummary;
  anchor: HTMLButtonElement;
  onClose: (restoreFocus: boolean) => void;
  onRename: (topic: TopicSummary) => void;
  onPin: (topicId: string, pinned: boolean) => void;
  onArchive: (topicId: string, archived: boolean) => void;
  onDelete: (topic: TopicSummary) => void;
}

const MENU_MARGIN = 8;
const MENU_GAP = 4;

export function TopicOverflowMenu({
  topic,
  anchor,
  onClose,
  onRename,
  onPin,
  onArchive,
  onDelete,
}: TopicOverflowMenuProps) {
  const menuId = topicMenuDomId(topic.id);
  const menuRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  const [position, setPosition] = useState<MenuPosition | null>(null);
  const actionOrder = topicMenuActionOrder(topic);

  useLayoutEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useLayoutEffect(() => {
    const menuElement = menuRef.current;
    if (!menuElement) return;
    const menuNode: HTMLDivElement = menuElement;

    function updatePosition() {
      if (!menuRef.current || !anchor.isConnected) {
        onCloseRef.current(false);
        return;
      }
      const anchorRect = anchor.getBoundingClientRect();
      const menuRect = menuRef.current.getBoundingClientRect();
      setPosition(computeMenuPosition(anchorRect, menuRect, window.innerWidth, window.innerHeight));
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (!menuNode.contains(target) && !anchor.contains(target)) onCloseRef.current(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current(true);
      }
    }

    updatePosition();
    const frame = window.requestAnimationFrame(() => {
      updatePosition();
      menuNode.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    });
    document.addEventListener("pointerdown", handlePointerDown, true);
    document.addEventListener("keydown", handleKeyDown, true);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", handlePointerDown, true);
      document.removeEventListener("keydown", handleKeyDown, true);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [anchor]);

  function moveFocus(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      if (event.key === "Tab") onClose(false);
      return;
    }
    event.preventDefault();
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)'));
    if (items.length === 0) return;
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Home") items[0].focus();
    else if (event.key === "End") items[items.length - 1].focus();
    else if (event.key === "ArrowDown") items[(current + 1 + items.length) % items.length].focus();
    else items[(current - 1 + items.length) % items.length].focus();
  }

  const menu = (
    <div
      ref={menuRef}
      id={menuId}
      className="topic-menu topic-menu--portal"
      role="menu"
      aria-label={`Actions for ${topic.title}`}
      data-placement={position?.placement}
      style={{
        left: position?.left ?? 0,
        top: position?.top ?? 0,
        visibility: position ? "visible" : "hidden",
      }}
      onKeyDown={moveFocus}
    >
      {actionOrder.includes("rename") ? (
        <button role="menuitem" type="button" onClick={() => { onRename(topic); onClose(false); }}>
          <Pencil size={14} aria-hidden="true" /> Rename
        </button>
      ) : null}
      {actionOrder.includes("pin") || actionOrder.includes("unpin") ? (
        <button role="menuitem" type="button" onClick={() => { onPin(topic.id, !topic.pinned); onClose(true); }}>
          {topic.pinned ? <PinOff size={14} aria-hidden="true" /> : <Pin size={14} aria-hidden="true" />}
          {topic.pinned ? "Unpin" : "Pin"}
        </button>
      ) : null}
      <button role="menuitem" type="button" onClick={() => { onArchive(topic.id, !topic.archived); onClose(true); }}>
        {topic.archived ? <ArchiveRestore size={14} aria-hidden="true" /> : <Archive size={14} aria-hidden="true" />}
        {topic.archived ? "Unarchive" : "Archive"}
      </button>
      <button className="topic-menu__danger" role="menuitem" type="button" onClick={() => { onDelete(topic); onClose(false); }}>
        <Trash2 size={14} aria-hidden="true" /> Delete
      </button>
    </div>
  );

  return typeof document === "undefined" ? null : createPortal(menu, document.body);
}

export function computeMenuPosition(
  anchor: Pick<DOMRect, "left" | "right" | "top" | "bottom">,
  menu: Pick<DOMRect, "width" | "height">,
  viewportWidth: number,
  viewportHeight: number,
): MenuPosition {
  const availableBelow = viewportHeight - anchor.bottom - MENU_MARGIN;
  const availableAbove = anchor.top - MENU_MARGIN;
  const placement = availableBelow >= menu.height || availableBelow >= availableAbove ? "below" : "above";
  const desiredTop = placement === "below" ? anchor.bottom + MENU_GAP : anchor.top - menu.height - MENU_GAP;
  const top = clamp(desiredTop, MENU_MARGIN, Math.max(MENU_MARGIN, viewportHeight - menu.height - MENU_MARGIN));
  const desiredLeft = anchor.right - menu.width;
  const left = clamp(desiredLeft, MENU_MARGIN, Math.max(MENU_MARGIN, viewportWidth - menu.width - MENU_MARGIN));
  return { left, top, placement };
}

export function topicMenuActionOrder(topic: Pick<TopicSummary, "archived" | "pinned">): TopicMenuActionId[] {
  if (topic.archived) return ["unarchive", "delete"];
  return ["rename", topic.pinned ? "unpin" : "pin", "archive", "delete"];
}

export function topicMenuDomId(topicId: string): string {
  const safeId = topicId.replace(/[^a-zA-Z0-9_-]/g, "-");
  return `topic-actions-${safeId || "topic"}`;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}
