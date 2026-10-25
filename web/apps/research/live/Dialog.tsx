import { useEffect, useRef, type ReactNode } from 'react';
import { IconX } from '@tabler/icons-react';

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    const trigger = document.activeElement as HTMLElement | null;
    dialog.showModal();
    return () => { dialog.close(); trigger?.focus(); };
  }, []);
  return <dialog ref={ref} className="rw-dialog" aria-label={title} onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <header><h2>{title}</h2><button aria-label="关闭" onClick={onClose}><IconX/></button></header>{children}
  </dialog>;
}
