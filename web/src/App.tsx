import { DemoBar } from "./components/DemoBar";
import { Topbar } from "./components/Topbar";
import { useDemo } from "./hooks";
import { Accuracy } from "./pages/Accuracy";
import { IncidentDetail } from "./pages/IncidentDetail";
import { IncidentList } from "./pages/IncidentList";
import { useRoute } from "./route";

export function App() {
  const route = useRoute();
  const demo = useDemo();
  return (
    <>
      <Topbar demo={demo} />
      <DemoBar demo={demo} />
      <main>
        {route.name === "accuracy" ? <Accuracy /> : route.name === "detail" ? <IncidentDetail id={route.id} /> : <IncidentList filters={route.filters} />}
      </main>
    </>
  );
}
