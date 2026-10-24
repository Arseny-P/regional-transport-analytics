import React, { useState, useEffect, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Layout from '../layout/Layout';
import {
  DEFAULT_TRANSPORT_MODE,
  TRANSPORT_MODES,
  TRANSPORT_MODE_LABELS,
} from '@/entities/transport-mode';
import { bboxToQuery, buildUrl, request } from '@/shared/api';

export default function ResultPage() {
  const location = useLocation();
  const navigate = useNavigate();

  const resultData = location.state || null;

  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState('mst_length');
  const [mode, setMode] = useState(resultData?.mode || DEFAULT_TRANSPORT_MODE);
  const [mapKey, setMapKey] = useState(Date.now());
  const [mapSrcState, setMapSrcState] = useState(null);

  useEffect(() => {
    setLoading(true);
  }, [mapKey]);

  const defaultMapSrc = useMemo(() => {
    if (!resultData) return '';
    const query = bboxToQuery(resultData.bbox);

    if (mode === 'all') return buildUrl('/map/all', query);

    return buildUrl('/map', { ...query, mode });
  }, [resultData, mode]);

  const mapSrc = mapSrcState || defaultMapSrc;

  const analyzeMetric = async () => {
    if (!resultData) return;
    try {
      setLoading(true);

      const data = await request('/metrics', {
        params: { metric, ...bboxToQuery(resultData.bbox), mode },
      });

      if (data.status !== 'ok') {
        alert('Анализ не удался: ' + (data.message || 'unknown'));
        setLoading(false);
        return;
      }

      setMapSrcState(buildUrl(data.map_path));
      setMapKey(Date.now());
    } catch (err) {
      console.error(err);
      alert('Ошибка при анализе метрики! ' + (err.message || ''));
      setLoading(false);
    }
  };

  const sidebarContent = (
    <>
      <h3 style={{ marginTop: 0 }}>📊 Результаты анализа</h3>

      {resultData ? (
        <>
          <div style={{ marginTop: '8px' }}>
            <h4>Режим маршрута:</h4>
            <select
              value={mode}
              onChange={(e) => {
                setMode(e.target.value);
                setMapSrcState(null);
                setMapKey(Date.now());
              }}
              style={{ width: '100%', padding: '6px', borderRadius: '6px' }}
            >
              {TRANSPORT_MODES.map((m) => (
                <option key={m} value={m}>
                  {TRANSPORT_MODE_LABELS[m]}
                </option>
              ))}
            </select>
          </div>

          <div style={{ marginTop: '15px' }}>
            <h4>Метрика графа:</h4>
            {[
              'degree_centrality',
              'closeness_centrality',
              'betweenness_centrality',
              'pagerank',
            ].map((m) => (
              <label key={m} style={{ display: 'block', marginBottom: '4px' }}>
                <input
                  type="radio"
                  value={m}
                  checked={metric === m}
                  onChange={(e) => setMetric(e.target.value)}
                  disabled={mode === 'all1'}
                />{' '}
                {m}
              </label>
            ))}
            {mode !== 'all1' ? (
              <button
                onClick={analyzeMetric}
                style={{
                  marginTop: '10px',
                  width: '100%',
                  padding: '8px',
                  borderRadius: '6px',
                  backgroundColor: '#0f62fe',
                  color: 'white',
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                Анализ метрики
              </button>
            ) : (
              <p style={{ fontSize: '14px', color: '#666', marginTop: '10px' }}>
                Метрики недоступны для отображения всех режимов одновременно.
              </p>
            )}
          </div>
        </>
      ) : (
        <p style={{ fontSize: '14px', color: 'red' }}>
          Нет данных анализа. Вернитесь на предыдущую страницу.
        </p>
      )}

      <button
        onClick={() => navigate('/analysis')}
        style={{
          marginTop: '450px',
          width: '100%',
          padding: '10px',
          backgroundColor: '#e6e6e6',
          border: 'none',
          borderRadius: '6px',
          cursor: 'pointer',
        }}
      >
        Новый анализ
      </button>
    </>
  );

  return (
    <div style={{ width: '100%', height: '100%', position: 'relative' }}>
      <Layout sidebarContent={sidebarContent}>
        <div style={{ width: '100%', height: '100%', position: 'relative' }}>
          {mapSrc && (
            <>
              {loading && (
                <div
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    height: '100%',
                    display: 'flex',
                    justifyContent: 'center',
                    alignItems: 'center',
                    backgroundColor: 'rgba(255,255,255,0.8)',
                    zIndex: 1000,
                    flexDirection: 'column',
                  }}
                >
                  <div
                    style={{
                      border: '6px solid #f3f3f3',
                      borderTop: '6px solid #0f62fe',
                      borderRadius: '50%',
                      width: '50px',
                      height: '50px',
                      animation: 'spin 1s linear infinite',
                      marginBottom: '12px',
                    }}
                  ></div>
                  <style>{`
                                        @keyframes spin {
                                            0% { transform: rotate(0deg); }
                                            100% { transform: rotate(360deg); }
                                        }
                                    `}</style>
                  <span
                    style={{
                      fontSize: '16px',
                      fontWeight: 'bold',
                      color: '#0f62fe',
                    }}
                  >
                    Загрузка карты...
                  </span>
                </div>
              )}

              <iframe
                key={mapKey}
                src={mapSrc}
                title="Map"
                style={{ width: '100%', height: '100%', border: 'none' }}
                onLoad={() => setLoading(false)}
              />
            </>
          )}
        </div>
      </Layout>
    </div>
  );
}
