import React from 'react';
import { createRoot } from 'react-dom/client';
import ResearchDemoApp from './research-demo-composition.js';
import './styles.css';

createRoot(document.getElementById('root')!).render(<React.StrictMode><ResearchDemoApp/></React.StrictMode>);
