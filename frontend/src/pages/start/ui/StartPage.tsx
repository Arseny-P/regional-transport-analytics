import { useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import { AppSidebar } from '@/widgets/app-layout';
import styles from './StartPage.module.css';
import { MapView } from '@/widgets/map-view';
import { useNavigate } from 'react-router-dom';
import { Button, Message } from '@/shared/ui';
import { RegionBoundary, uploadRegion, useRegion, useRegions } from '@/entities/region';
import type { Region } from '@/entities/region';
import { getRegionUploadError, validateRegionFile } from '../lib/regionUpload';

type UploadStatus = { type: 'idle' | 'loading' } | { type: 'success' | 'error'; message: string };

export function StartPage() {
  const navigate = useNavigate();

  const steps = [
    {
      title: 'Добро пожаловать!',
      description:
        'Сервис помогает исследовать связи между логистическими объектами выбранной территории. Постройте граф транспортной сети и изучите её показатели.',
    },
    {
      title: 'Назначение',
      description:
        'Цель — представить логистические объекты и потенциальные транспортные связи между ними, чтобы анализировать структуру и доступность транспортно-логистической сети одного или нескольких регионов.',
    },
  ];
  const [step, setStep] = useState(0);
  const currentStep = steps[step];

  const [regionId, setRegionId] = useState('');
  const [uploadedRegion, setUploadedRegion] = useState<Region | null>(null);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>({ type: 'idle' });
  const fileInput = useRef<HTMLInputElement>(null);
  const { regions, error: listError, addRegion } = useRegions();
  const selectedUpload = uploadedRegion?.region_id === regionId ? uploadedRegion : null;
  const { region: fetchedRegion, error: regionError } = useRegion(
    selectedUpload ? null : regionId || null
  );
  const region = selectedUpload ?? (fetchedRegion?.region_id === regionId ? fetchedRegion : null);
  const error = listError ?? regionError;
  const isUploading = uploadStatus.type === 'loading';

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    input.value = '';
    if (!file || isUploading) return;

    setUploadStatus({ type: 'loading' });
    const validationError = await validateRegionFile(file);
    if (validationError) {
      setUploadStatus({ type: 'error', message: validationError });
      return;
    }

    try {
      const uploaded = await uploadRegion(file);
      addRegion({ region_id: uploaded.region_id, name: file.name });
      setUploadedRegion(uploaded);
      setRegionId(uploaded.region_id);
      setUploadStatus({ type: 'success', message: 'Регион загружен.' });
    } catch (uploadError) {
      setUploadStatus({ type: 'error', message: getRegionUploadError(uploadError) });
    }
  }

  const sidebarContent = (
    <div className={styles.panel}>
      <h1 className={styles.title}>Загрузите регион</h1>

      <p className={styles.description}>Исследуйте связи транспортной сети выбранной территории.</p>

      <div className={styles.uploadZone}>
        <p id="region-file-hint" className={styles.hint}>
          Выберите GeoJSON с границей региона размером до 20 МБ.
        </p>
        <input
          ref={fileInput}
          type="file"
          accept=".geojson,.json,application/geo+json,application/json"
          onChange={handleFileChange}
          disabled={isUploading}
          hidden
        />
        <Button
          aria-describedby="region-file-hint"
          disabled={isUploading}
          onClick={() => fileInput.current?.click()}
        >
          Выбрать файл
        </Button>
        {isUploading && <p role="status">Загружаем регион…</p>}
        {uploadStatus.type === 'success' && <p role="status">{uploadStatus.message}</p>}
        {uploadStatus.type === 'error' && (
          <p className={styles.error} role="alert">
            {uploadStatus.message}
          </p>
        )}
      </div>

      <label className={styles.regions}>
        Или выберите загруженный регион
        <select
          className={styles.select}
          value={regionId}
          onChange={(e) => setRegionId(e.target.value)}
          disabled={!regions?.length}
        >
          <option value="">
            {regions?.length
              ? 'Выберите регион'
              : listError
                ? 'Список регионов недоступен'
                : regions
                  ? 'Регионов пока нет'
                  : 'Загрузка...'}
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
        disabled={!region || isUploading}
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

        {!region && (
          <>
            <div className={styles.overlay}></div>
            <section className={styles.infoCard}>
              <Message
                title={currentStep.title}
                description={currentStep.description}
                actions={
                  <Button onClick={() => setStep(step === 0 ? 1 : 0)}>
                    {' '}
                    {step === 0 ? 'Подробнее' : 'Назад'}{' '}
                  </Button>
                }
              />
            </section>
          </>
        )}
      </div>
    </>
  );
}
