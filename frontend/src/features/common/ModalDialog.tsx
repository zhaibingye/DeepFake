import type { Dispatch, SetStateAction } from 'react'

export type DialogState = {
  mode: 'confirm' | 'prompt'
  title: string
  message: string
  confirmLabel: string
  cancelLabel: string
  value: string
  resolve: (value: boolean | string | null) => void
}

type ModalDialogProps = {
  dialogState: DialogState
  setDialogState: Dispatch<SetStateAction<DialogState | null>>
  closeDialog: (value: boolean | string | null) => void
}

export function ModalDialog({ dialogState, setDialogState, closeDialog }: ModalDialogProps) {
  return (
    <div className="modal-backdrop" onClick={() => closeDialog(null)} role="presentation">
      <div aria-modal="true" className="modal-card" onClick={(event) => event.stopPropagation()} role="dialog">
        <div className="modal-header">
          <h3>{dialogState.title}</h3>
          <p>{dialogState.message}</p>
        </div>
        {dialogState.mode === 'prompt' ? (
          <input
            autoFocus
            className="modal-input"
            onChange={(event) => setDialogState((current) => (current ? { ...current, value: event.target.value } : current))}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                closeDialog(dialogState.value)
              }
            }}
            value={dialogState.value}
          />
        ) : null}
        <div className="modal-actions">
          <button className="ghost-btn" onClick={() => closeDialog(null)} type="button">
            {dialogState.cancelLabel}
          </button>
          <button
            className={dialogState.confirmLabel === '删除' ? 'primary-btn danger-fill' : 'primary-btn'}
            onClick={() => closeDialog(dialogState.mode === 'prompt' ? dialogState.value : true)}
            type="button"
          >
            {dialogState.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
