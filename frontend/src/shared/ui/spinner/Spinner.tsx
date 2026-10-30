import styles from './Spinner.module.css';

interface SpinnerProps {
  size?: 'small' | 'medium' | 'large';
  color?: string;
  text?: string;
}

export function Spinner({
  size = 'medium',
  color,
  text = 'Загрузка...',
}: SpinnerProps) {
  return (
    <div className={styles.container} role="status">
      <svg
        className={[styles.spinner, styles[size]].join(' ')}
        viewBox="0 0 40 40"
        fill="none"
        stroke={color ?? 'currentColor'}
        aria-hidden="true"
      >
        <circle className={styles.track} cx="20" cy="20" r="17" />
        <circle className={styles.arc} cx="20" cy="20" r="17" />
      </svg>
      {text ? (
        <span className={styles.text}>{text}</span>
      ) : (
        <span className={styles.visuallyHidden}>Загрузка</span>
      )}
    </div>
  );
}
