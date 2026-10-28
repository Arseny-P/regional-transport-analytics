import { AppSidebar } from '@/widgets/app-layout';
import styles from './StartPage.module.css';
import { MapView } from '@/widgets/map-view';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/shared/ui';

export function StartPage() {
  const navigate = useNavigate();

  const sidebarContent = (
    <div className={styles.panel}>
      <h1 className={styles.title}>Загрузите регион</h1>

      <p className={styles.description}>Исследуйте связи транспортной сети выбранной территории.</p>

      <div className={styles.uploadZone}>
        <p>Перетащите GeoJSON сюда</p>

        {/* На данный момент просто переносит на страницу выбора точек */}
        <Button onClick={() => navigate('/analysis')}>Выбрать файл</Button>
      </div>

      <p className={styles.hint}>Файл должен содержать границу региона.</p>
    </div>
  );

  return (
    <>
      <AppSidebar>{sidebarContent}</AppSidebar>
      <MapView />
    </>
  );
}
