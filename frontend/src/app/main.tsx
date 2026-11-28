import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { API_MOCKS_ENABLED } from '@/shared/config';

import { App } from './App';

import './styles/index.css';
import 'leaflet/dist/leaflet.css';
import './leafletIcons';

if (API_MOCKS_ENABLED) {
  const { worker } = await import('./mocks/browser');
  await worker.start({ onUnhandledFrame: 'bypass' });
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
