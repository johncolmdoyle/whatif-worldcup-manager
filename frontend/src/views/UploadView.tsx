import { useCallback, useRef, useState, type DragEvent, type ChangeEvent } from "react";
import { useAppContext } from "../context/AppContext";
import { useApi } from "../hooks/useApi";
import { uploadPdf, ApiError } from "../api/client";

export function UploadView() {
  const { state, dispatch } = useAppContext();
  const { withSessionCheck } = useApi();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

  const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50 MB

  const handleFile = useCallback(
    async (file: File) => {
      if (file.type !== "application/pdf") {
        dispatch({ type: "UPLOAD_ERROR", payload: "Only PDF files are accepted" });
        return;
      }

      if (file.size > MAX_FILE_SIZE) {
        dispatch({ type: "UPLOAD_ERROR", payload: "File exceeds 50 MB limit" });
        return;
      }

      dispatch({ type: "UPLOAD_START" });
      setIsUploading(true);

      try {
        const result = await withSessionCheck(() => uploadPdf(file));
        dispatch({
          type: "EXTRACTION_COMPLETE",
          payload: {
            matchData: result.matchData,
            missingFields: result.missingFields,
          },
        });
      } catch (error) {
        const message =
          error instanceof ApiError
            ? error.message
            : "An unexpected error occurred during upload.";
        dispatch({ type: "UPLOAD_ERROR", payload: message });
      } finally {
        setIsUploading(false);
      }
    },
    [dispatch, withSessionCheck]
  );

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragOver(false);

      if (isUploading) return;

      const file = e.dataTransfer.files[0];
      if (file) {
        handleFile(file);
      }
    },
    [handleFile, isUploading]
  );

  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleInputChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        handleFile(file);
      }
    },
    [handleFile]
  );

  const handleClick = useCallback(() => {
    if (isUploading) return;
    fileInputRef.current?.click();
  }, [isUploading]);

  const handleClearError = useCallback(() => {
    dispatch({ type: "CLEAR_ERROR" });
  }, [dispatch]);

  return (
    <div className="flex flex-col items-center justify-center w-full max-w-xl mx-auto px-4 py-8">
      <div
        role="button"
        tabIndex={isUploading ? -1 : 0}
        aria-label="Upload PDF file. Drag and drop or click to browse."
        aria-disabled={isUploading}
        className={`
          w-full p-10 rounded-lg border-2 border-dashed
          transition-colors duration-200 text-center
          ${isUploading ? "cursor-not-allowed opacity-60" : "cursor-pointer"}
          ${
            isDragOver && !isUploading
              ? "border-blue-500 bg-blue-50"
              : "border-gray-300 bg-gray-50 hover:border-gray-400 hover:bg-gray-100"
          }
        `}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={handleClick}
        onKeyDown={(e) => {
          if (isUploading) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleClick();
          }
        }}
      >
        {isUploading ? (
          <div className="flex flex-col items-center">
            <svg
              className="animate-spin h-10 w-10 text-blue-500"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
            <p className="mt-4 text-sm text-gray-600">Processing PDF...</p>
          </div>
        ) : (
          <>
            <svg
              className="mx-auto h-12 w-12 text-gray-400"
              stroke="currentColor"
              fill="none"
              viewBox="0 0 48 48"
              aria-hidden="true"
            >
              <path
                d="M28 8H12a4 4 0 00-4 4v20m32-12v8m0 0v8a4 4 0 01-4 4H12a4 4 0 01-4-4v-4m32-4l-3.172-3.172a4 4 0 00-5.656 0L28 28M8 32l2.828-2.828a4 4 0 015.656 0L28 40"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>

            <p className="mt-4 text-sm text-gray-600">
              Drag &amp; drop a FIFA match report PDF or click to browse
            </p>
            <p className="mt-1 text-xs text-gray-500">PDF files only</p>
          </>
        )}
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        onChange={handleInputChange}
        disabled={isUploading}
        aria-hidden="true"
        tabIndex={-1}
      />

      {state.error && (
        <div
          role="alert"
          className="mt-4 w-full p-3 rounded-md bg-red-50 border border-red-200 text-red-700 text-sm"
        >
          <p>{state.error}</p>
          <button
            type="button"
            onClick={handleClearError}
            className="mt-2 text-sm font-medium text-red-800 underline hover:text-red-900 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 rounded"
          >
            Upload different file
          </button>
        </div>
      )}
    </div>
  );
}
