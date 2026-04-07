import { BrowserRouter, Routes, Route, NavLink, useNavigate, useParams, useLocation } from 'react-router-dom';
import { JobTracker } from './components/JobTracker';
import { JobDetail } from './components/JobDetail';
import { DocumentViewer } from './components/DocumentViewer';
import { SourcesWorkspace } from './components/SourcesWorkspace';
import { QualityDashboard } from './components/QualityDashboard';
import { GenerationPage } from './components/GenerationPage';
import { ChatInterface } from './components/ChatInterface';
import { AgentChat } from './components/AgentChat';
import { SkillsPage } from './components/SkillsPage';
import { SearchPage } from './components/SearchPage';
import { ListPage } from './components/ListPage';
import { ResearchPage } from './components/ResearchPage';
import { loadAllJobs } from './data/loadJobs';
import './styles/index.css';
import './styles/skills.css';

const jobs = loadAllJobs();

function TrackerPage() {
  return <JobTracker jobs={jobs} />;
}

function DetailPage() {
  const { index } = useParams<{ index: string }>();
  const navigate = useNavigate();
  const job = jobs.find(j => j.index === parseInt(index || '1', 10));

  if (!job) {
    return <div className="error">Job not found</div>;
  }

  return <JobDetail job={job} onBack={() => navigate('/')} />;
}

/** Documents shell with Applications / Sources sub-tabs. */
function DocumentsLayout() {
  const location = useLocation();
  const isSources = location.pathname.startsWith('/documents/sources');

  return (
    <div className="documents-layout">
      <div className="documents-subnav" role="tablist" aria-label="Documents sections">
        <NavLink
          to="/documents"
          end
          role="tab"
          className={({ isActive }) => `subnav-tab${isActive ? ' active' : ''}`}
        >
          Applications
        </NavLink>
        <NavLink
          to="/documents/sources"
          role="tab"
          className={({ isActive }) => `subnav-tab${isActive ? ' active' : ''}`}
        >
          Sources
        </NavLink>
      </div>
      <div className="documents-content">
        {isSources ? <SourcesWorkspace /> : <DocumentViewer jobs={jobs} />}
      </div>
    </div>
  );
}

function QualityPage() {
  return <QualityDashboard jobs={jobs} />;
}

function GenerationPageWrapper() {
  return <GenerationPage jobs={jobs} />;
}

function ChatPage() {
  return <ChatInterface />;
}

function AgentPage() {
  return <AgentChat />;
}

function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <header className="app-header">
          <h1>Job Application Tracker</h1>
          <nav className="app-nav" aria-label="Main navigation">
            <NavLink to="/" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`} end>Tracker</NavLink>
            <NavLink to="/documents" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Documents</NavLink>
            <NavLink to="/search" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Search</NavLink>
            <NavLink to="/lists" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Lists</NavLink>
            <NavLink to="/research" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Research</NavLink>
            <NavLink to="/quality" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Quality</NavLink>
            <NavLink to="/generation" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Generate</NavLink>
            <NavLink to="/chat" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Chat</NavLink>
            <NavLink to="/agent" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Agent</NavLink>
            <NavLink to="/skills" className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}>Skills</NavLink>
          </nav>
        </header>
        <main className="app-main">
          <Routes>
            {/* Core */}
            <Route path="/" element={<TrackerPage />} />
            <Route path="/job/:index" element={<DetailPage />} />
            <Route path="/documents" element={<DocumentsLayout />} />
            <Route path="/documents/sources" element={<DocumentsLayout />} />
            <Route path="/documents/:index" element={<DocumentsLayout />} />
            {/* Discovery (v1.2) */}
            <Route path="/search" element={<SearchPage />} />
            <Route path="/lists" element={<ListPage />} />
            <Route path="/research" element={<ResearchPage />} />
            {/* Quality & Generation */}
            <Route path="/quality" element={<QualityPage />} />
            <Route path="/quality/:index" element={<QualityPage />} />
            <Route path="/generation" element={<GenerationPageWrapper />} />
            <Route path="/generation/:index" element={<GenerationPageWrapper />} />
            {/* Assistant */}
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/chat/:index" element={<ChatPage />} />
            <Route path="/agent" element={<AgentPage />} />
            <Route path="/skills" element={<SkillsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
