import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import styles from './AppLayout.module.css';

export function AppLayout() {
  const [sidebarNode, setSidebarNode] = useState<HTMLDivElement | null>(null);

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        Анализ транспортной сети
      </header>
      <div className={styles.body}>
        <aside className={styles.sidebar}>
          <div ref={setSidebarNode} />
        </aside>
        <main className={styles.content}>
          <Outlet context={sidebarNode} />
        </main>
      </div>
      <footer className={styles.footer}>
        <span>Карта © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors</span>
        <a href="https://github.com/Arseny-P/regional-transport-analytics" target="_blank" rel="noopener noreferrer">Наш GitHub</a>
      </footer>
    </div>
  );
}

