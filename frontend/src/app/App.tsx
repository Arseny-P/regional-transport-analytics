import { BrowserRouter as Router, Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from '@/widgets/app-layout';
import { StartPage } from '@/pages/start';
import { AnalysisPage } from '@/pages/analysis';
import { ResultPage } from '@/pages/result';

export function App() {
  return (
    <Router>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Navigate to="/start" replace />} />
          <Route path="/start" element={<StartPage />} />
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="/result" element={<ResultPage />} />
        </Route>
      </Routes>
    </Router>
  );
}
