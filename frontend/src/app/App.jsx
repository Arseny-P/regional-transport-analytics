import React from 'react';
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';

import { AppLayout } from '@/widgets/app-layout';

import { StartPage } from '@/pages/start';
import { AnalysisPage } from '@/pages/analysis';
import { ResultPage } from '@/pages/result';


export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/start" element={<StartPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="/result" element={<ResultPage />} />
      </Routes>
    </Router>
  );
}
