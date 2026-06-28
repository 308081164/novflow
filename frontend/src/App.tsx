import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import ProtectedRoute from "./ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import NewBookPage from "./pages/NewBookPage";
import BookOverviewPage from "./pages/BookOverviewPage";
import SetupWizardPage from "./pages/SetupWizardPage";
import SetupChatPage from "./pages/SetupChatPage";
import WorldviewPage from "./pages/WorldviewPage";
import CharactersPage from "./pages/CharactersPage";
import OutlinePage from "./pages/OutlinePage";
import BookResourcesPage from "./pages/BookResourcesPage";
import ChapterEditorPage from "./pages/ChapterEditorPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/new" element={<NewBookPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/books/:bookId" element={<BookOverviewPage />} />
            <Route path="/books/:bookId/setup" element={<SetupChatPage />} />
            <Route path="/books/:bookId/setup/classic" element={<SetupWizardPage />} />
            <Route path="/books/:bookId/worldview" element={<WorldviewPage />} />
            <Route path="/books/:bookId/characters" element={<CharactersPage />} />
            <Route path="/books/:bookId/outline" element={<OutlinePage />} />
            <Route path="/books/:bookId/resources" element={<BookResourcesPage />} />
            <Route path="/books/:bookId/write/:chapterNo" element={<ChapterEditorPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
