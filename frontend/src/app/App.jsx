import React from 'react';
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';

import { Layout } from '@/widgets/layout';

import { AnalysisPage } from '@/pages/analysis';
import { ResultPage } from '@/pages/result';

export default function App() {
  return (
    <Router>
      <Layout>
        <Routes>
          <Route path="/" element={<AnalysisPage />} />
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="/result" element={<ResultPage />} />
        </Routes>
      </Layout>
    </Router>
  );
}
