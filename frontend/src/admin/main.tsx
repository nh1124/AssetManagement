import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import '../studio/theme.css';
import './admin.css';
import AdminApp from './AdminApp';

createRoot(document.getElementById('root')!).render(<BrowserRouter><AdminApp /></BrowserRouter>);
