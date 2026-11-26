import { deleteAllInvestigations } from "../api";
import { ConfirmDelete } from "./ConfirmDelete";

export function DeleteAllButton({ finished, running }: { finished: number; running: number }) {
  const what = finished === 1 ? "A investigação concluída será apagada" : `As ${finished} investigações concluídas serão apagadas`;
  return (
    <ConfirmDelete
      label="Apagar todas"
      disabled={finished === 0}
      title="Apagar todo o histórico?"
      message={`${what} para sempre.${running > 0 ? ` As ${running} em andamento ficam.` : ""} Não há como desfazer.`}
      confirmLabel="Apagar todas"
      onConfirm={async () => {
        await deleteAllInvestigations();
      }}
    />
  );
}
