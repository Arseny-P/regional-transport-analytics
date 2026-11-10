import { useState } from 'react';
import { AppSidebar } from '@/widgets/app-layout';
import styles from './StartPage.module.css';
import { MapView } from '@/widgets/map-view';
import { useNavigate } from 'react-router-dom';
import { Button, Message } from '@/shared/ui';
import { RegionBoundary, useRegion, useRegions } from '@/entities/region';



export function StartPage() {
  const navigate = useNavigate();

  const steps = [
    {
      
      title: "Добро пожаловать!" ,
      description: "Сервис помогает исследовать связи между логистическими объектами выбранной территории. Постройте граф транспортной сети и изучите её показатели."
    },
    {
      title: "Назначение",
      description: "Цель — представить логистические объекты и потенциальные транспортные связи между ними, чтобы анализировать структуру и доступность транспортно-логистической сети одного или нескольких регионов."
    }
  ]
  const [step, setStep] = useState(0);
  const currentStep = steps[step];
  
  const [regionId, setRegionId] = useState('');
  const { regions, error: listError } = useRegions();
  const { region, error: regionError } = useRegion(regionId || null);
  const error = listError ?? regionError;

  const sidebarContent = (
    <div className={styles.panel}>
      <h1 className={styles.title}>Загрузите регион</h1>

      <p className={styles.description}>Исследуйте связи транспортной сети выбранной территории.</p>

      <div className={styles.uploadZone}>
        <p>Перетащите GeoJSON сюда</p>
        <Button disabled>Выбрать файл</Button>
      </div>

      <p className={styles.hint}>Файл должен содержать границу региона.</p>

      <label className={styles.regions}>
        Или выберите загруженный регион
        <select className={styles.select}
          value={regionId}
          onChange={(e) => setRegionId(e.target.value)}
          disabled={!regions?.length}
        >
          <option value="">
            {!regions ? 'Загрузка...' : regions.length ? 'Выберите регион' : 'Регионов пока нет'}
          </option>
          {regions?.map((r) => (
            <option key={r.region_id} value={r.region_id}>
              {r.name}
            </option>
          ))}
        </select>
      </label>

      {error && <p className={styles.error}>{error.message}</p>}

      <Button
        disabled={!region}
        onClick={() => navigate(`/analysis?region_id=${encodeURIComponent(regionId)}`)}
      >
        Продолжить
      </Button>
    </div>
  );

  return (
    <>
      <AppSidebar>{sidebarContent}</AppSidebar>
      <div className={styles.MapContainer}>
        <MapView>{region && <RegionBoundary region={region} />}</MapView>

        <div className={styles.overlay}>     
        </div>
        <section className={styles.infoCard}>
          <Message 
          title={currentStep.title}
          description={currentStep.description}
          actions={<Button onClick={() => setStep(step === 0 ? 1 : 0)}> {step === 0 ? 'Подробнее' : 'Назад'} </Button>}
          />
        </section>
      </div>
    </>
  );
}
