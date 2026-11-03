import { BrowserRouter, Route, Routes } from "react-router";
import { Shell } from "./components/Shell";
import { LiveProvider } from "./live";
import { Costs } from "./pages/Costs";
import { CvDetailPage } from "./pages/CvDetail";
import { Cvs } from "./pages/Cvs";
import { Dashboard } from "./pages/Dashboard";
import { EditPage } from "./pages/EditPage";
import { RunPage } from "./pages/run/RunPage";

export function App() {
  return (
    <BrowserRouter>
      <LiveProvider>
        <Shell>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/cvs" element={<Cvs />} />
            <Route path="/cvs/:id" element={<CvDetailPage />} />
            <Route path="/runs/:id" element={<RunPage />} />
            <Route path="/runs/:id/edit" element={<EditPage />} />
            <Route path="/costs" element={<Costs />} />
            <Route path="*" element={<p className="page empty">Page not found.</p>} />
          </Routes>
        </Shell>
      </LiveProvider>
    </BrowserRouter>
  );
}
