import { useState, useCallback } from 'react';

interface RollbackButtonProps {
  checkpointId: string;
  onRollback: (checkpointId: string) => void;
  disabled?: boolean;
}

export function RollbackButton({ checkpointId, onRollback, disabled = false }: RollbackButtonProps) {
  const [confirming, setConfirming] = useState(false);

  const handleClick = useCallback(() => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    onRollback(checkpointId);
    setConfirming(false);
  }, [checkpointId, onRollback, confirming]);

  const handleCancel = useCallback(() => {
    setConfirming(false);
  }, []);

  if (confirming) {
    return (
      <div className="rollback-confirm">
        <span className="rollback-confirm-text">Revert changes?</span>
        <button
          type="button"
          className="rollback-confirm-btn rollback-confirm-yes"
          onClick={handleClick}
        >
          Yes, revert
        </button>
        <button
          type="button"
          className="rollback-confirm-btn rollback-confirm-no"
          onClick={handleCancel}
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      className="rollback-btn"
      onClick={handleClick}
      disabled={disabled}
      title="Undo this change"
    >
      Undo
    </button>
  );
}
