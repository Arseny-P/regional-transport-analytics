import React from 'react';
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';

import { Layout } from '@/widgets/layout';

import { AnalysisPage } from '@/pages/analysis';
import { ResultPage } from '@/pages/result';
import { StartPage } from '@/pages/start';

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<StartPage />} />
        <Route path="/analysis" element={<AnalysisPage />} />
        <Route path="/result" element={<ResultPage />} />
      </Routes>
    </Router>
  );
}
