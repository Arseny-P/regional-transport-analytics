import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useOutletContext } from 'react-router-dom';

export function AppSidebar({ children }: { children: ReactNode }) {
  const node = useOutletContext<HTMLElement | null>();
  return node && createPortal(children, node);
}
