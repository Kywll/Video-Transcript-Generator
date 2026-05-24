import { useState } from "react";

function ApiKeyManager({
    label,
    value,
    onChange,
    onSave,
    onDelete,
    saved
}) {

    const [isSaving, setIsSaving] = useState(false);

    return (
        <div className="mb-3">

            <label className="form-label">
                {label}
            </label>

            <div className="d-flex gap-2">

                <input
                    type="password"
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    className="form-control"
                    placeholder="Enter API key"
                />

                <button
                    className="btn btn-success"
                    onClick={async () => {
                        setIsSaving(true);
                        await onSave();
                        setIsSaving(false);
                    }}
                    disabled={isSaving}
                >
                    {isSaving ? "Saving..." : "Save"}
                </button>

                {saved && (
                    <button
                        className="btn btn-danger"
                        onClick={onDelete}
                    >
                        Delete
                    </button>
                )}

            </div>

            {saved && (
                <small className="text-success">
                    ✓ Saved
                </small>
            )}

        </div>
    );
}

export default ApiKeyManager;