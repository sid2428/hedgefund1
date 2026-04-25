import axios, { AxiosError } from "axios";

const baseURL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.response.use(
  (res) => res,
  (error: AxiosError<{ detail?: string }>) => {
    const detail =
      error.response?.data?.detail ||
      error.message ||
      "Unknown error";
    // Normalise the error shape so React Query renders something useful.
    return Promise.reject({
      status: error.response?.status,
      detail,
      raw: error,
    });
  }
);
