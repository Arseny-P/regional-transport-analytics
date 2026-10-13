import React from 'react';
import { BrowserRouter as Router, Route, Routes } from 'react-router-dom';

import Layout from './layout/Layout';

import AnalysisPage from './pages/AnalysisPage';
import ResultPage from './pages/ResultPage';

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
