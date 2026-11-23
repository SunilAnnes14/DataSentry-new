import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppProvider } from "./components/AppContext";
import Layout from "./components/Layout";
import Blockchain from "./pages/Blockchain";
import Network from "./pages/Network";
import Overview from "./pages/Overview";
import Performance from "./pages/Performance";
import Security from "./pages/Security";
import Settings from "./pages/Settings";
import "./styles/index.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <AppProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="network" element={<Network />} />
            <Route path="security" element={<Security />} />
            <Route path="blockchain" element={<Blockchain />} />
            <Route path="performance" element={<Performance />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppProvider>
  </StrictMode>
);
