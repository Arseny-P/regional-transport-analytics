import { Layout } from '@/widgets/layout';
import styles from './StartPage.module.css';
import { MapView } from '@/widgets/map-view';
import { useNavigate } from 'react-router-dom';



export function StartPage() {
  const navigate = useNavigate();
    
  const sidebarContent = (
    <div className={styles.panel}>
      <h1 className={styles.title}>Загрузите регион</h1>

      <p className={styles.description}>
        Исследуйте связи транспортной сети выбранной территории.
      </p>

      <div className={styles.uploadZone}>
        <p>Перетащите GeoJSON сюда</p>

        {/* На данный момент просто переносит на страницу выбора точек */}
        <button 
            type="button" 
            className={styles.button}
            onClick={() => navigate('/analysis')}
        >
          Выбрать файл 
        </button>
      </div>

      <p className={styles.hint}>
        Файл должен содержать границу региона.
      </p>
    </div>
  );

  return (
    <Layout sidebarContent={sidebarContent}>
      <MapView />
    </Layout>
  );
}