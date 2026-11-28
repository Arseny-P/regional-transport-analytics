import type { ReactNode } from 'react';
import styles from './Message.module.css';

interface MessageProps {
  title: string;
  description: string;
  variant?: 'error' | 'canceled';
  icon?: ReactNode;
  actions?: ReactNode;
}

export function Message({ title, description, variant, icon, actions }: MessageProps) {
  return (
    <section className={styles.message} aria-label={title} data-variant={variant}>
      <h2 className={styles.title} role={variant === 'canceled' ? 'status' : undefined}>
        {variant && (
          <span className={styles.badge} aria-hidden="true">
            {variant === 'error' ? '!' : '×'}
          </span>
        )}
        {title}
      </h2>

      {icon && <div className={styles.icon}>{icon}</div>}

      <p className={styles.description} role={variant === 'error' ? 'alert' : undefined}>
        {description}
      </p>

      {actions && <div className={styles.actions}>{actions}</div>}
    </section>
  );
}
