import { useCallback, useRef, useState } from "react";
import type { Document } from "../../types";
import * as api from "../../services/api";

interface Props {
  sessionId: string;
  documents: Document[];
  onRefresh: () => void;
}

export default function DocumentUpload({ sessionId, documents, onRefresh }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      setUploading(true);
      try {
        for (const file of Array.from(files)) {
          await api.uploadDocument(sessionId, file);
        }
        onRefresh();
      } catch (err) {
        console.error("Upload failed:", err);
      } finally {
        setUploading(false);
      }
    },
    [sessionId, onRefresh],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      if (e.dataTransfer.files.length) handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const handleDelete = async (docId: string) => {
    try {
      await api.deleteDocument(sessionId, docId);
      onRefresh();
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  return (
    <div className="space-y-3">
      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`rounded-lg border-2 border-dashed p-8 text-center transition-colors
          ${
            dragging
              ? "border-brand-teal-light bg-brand-teal-light/5"
              : "border-brand-light-gray-1 bg-brand-light-gray-2"
          }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) handleFiles(e.target.files);
            e.target.value = "";
          }}
        />

        <div className="space-y-2">
          {/* Upload icon */}
          <svg
            className="mx-auto h-10 w-10 text-brand-mid-gray"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 16V4m0 0l-4 4m4-4 4 4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"
            />
          </svg>

          <p className="font-body text-brand-gray text-sm">
            {uploading ? (
              <span className="text-brand-teal font-medium">Uploading...</span>
            ) : (
              <>
                Drag and drop files here, or{" "}
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="text-brand-teal hover:text-brand-teal-dark font-medium
                             underline underline-offset-2"
                >
                  browse
                </button>
              </>
            )}
          </p>
        </div>
      </div>

      {/* Uploaded documents list */}
      {documents.length > 0 && (
        <ul className="space-y-2">
          {documents.map((doc) => (
            <li
              key={doc.id}
              className="flex items-center justify-between rounded-lg bg-white px-4 py-3
                         shadow-sm border border-brand-light-gray-1"
            >
              <div className="flex items-center gap-3 min-w-0">
                {/* File icon */}
                <svg
                  className="h-5 w-5 shrink-0 text-brand-teal"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
                  />
                </svg>
                <span className="font-body text-sm text-brand-dark-gray truncate">
                  {doc.filename}
                </span>
              </div>

              <button
                onClick={() => handleDelete(doc.id)}
                className="shrink-0 ml-3 text-brand-mid-gray hover:text-red-500 transition-colors"
                title="Delete document"
              >
                <svg
                  className="h-5 w-5"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"
                  />
                </svg>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
