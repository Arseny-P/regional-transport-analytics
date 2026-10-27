// import { useState } from 'react';
import styles from './Layout.module.css';
import type { ReactNode } from 'react';

interface LayoutProps {
    children: ReactNode;
    sidebarContent?: ReactNode;
}

export default function Layout({ 
    children, 
    sidebarContent, 
}: LayoutProps) {
  return (
    <div className={styles.layout}>
        <header className={styles.header}>
            Анализ транспортной сети
        </header>

        <div className={styles.body}>
            <aside className={styles.sidebar}>
                {sidebarContent}
            </aside>

            <main className={styles.content}>
                {children}
            </main>
        </div>
    </div>
    
  );
}
