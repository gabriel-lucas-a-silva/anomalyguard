import { deleteInvestigation } from "../api";
import { ConfirmDelete } from "./ConfirmDelete";

export function DeleteButton({ id }: { id: string }) {
  return (
    <ConfirmDelete
      label="Apagar investigação"
      iconOnly
      title={`Apagar ${id}?`}
      message="O resultado, o gabarito e os dados gravados desta investigação somem para sempre. Não há como desfazer."
      confirmLabel="Apagar"
      onConfirm={async () => {
        await deleteInvestigation(id);
        window.location.hash = "#/";
      }}
    />
  );
}
