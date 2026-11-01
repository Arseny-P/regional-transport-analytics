import type { ReactNode } from 'react';
import styles from './Message.module.css';

interface MessageProps {
  title: string;
  description: string;
  icon?: ReactNode;
  actions?: ReactNode;
}

export function Message({
  title,
  description,
  icon,
  actions,
}: MessageProps) {
  return (
    <section className={styles.message} aria-label={title}>
      <h2 className={styles.title}>{title}</h2>

      {icon && <div className={styles.icon}>{icon}</div>}

      <p className={styles.description}>{description}</p>

      {actions && <div className={styles.actions}>{actions}</div>}
    </section>
  );
}