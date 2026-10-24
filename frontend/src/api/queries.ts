import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  api,
  ApiError,
  setCsrfToken,
  type LoginResult,
  type ProjectCreate,
  type ProjectDetail,
  type ProjectItem,
  type ProjectPatch,
  type SessionInfo,
} from "./client";

export const keys = {
  session: ["session"] as const,
  projects: (filter: string) => ["projects", filter] as const,
  project: (id: string) => ["project", id] as const,
};

export function useSession() {
  return useQuery({
    queryKey: keys.session,
    retry: false,
    staleTime: 60_000,
    queryFn: async () => {
      try {
        const info = await api<SessionInfo>("/api/session");
        setCsrfToken(info.csrf_token);
        return info;
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
  });
}

export function useLogin() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (senha: string) => api<LoginResult>("/api/session/login", { method: "POST", body: { senha } }),
    onSuccess: async (result) => {
      setCsrfToken(result.csrf_token);
      await client.invalidateQueries({ queryKey: keys.session });
    },
  });
}

export function useLogout() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api<void>("/api/session/logout", { method: "POST" }),
    onSuccess: () => {
      setCsrfToken(null);
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== "session" });
      client.setQueryData(keys.session, null);
    },
  });
}

export function useProjects(filter: string) {
  const query = filter === "todos" ? "?incluir_arquivados=1" : filter === "ativos" ? "" : `?status=${filter}`;
  return useQuery({
    queryKey: keys.projects(filter),
    queryFn: () => api<ProjectItem[]>(`/api/projects${query}`),
  });
}

export function useProject(id: string | undefined) {
  return useQuery({
    queryKey: keys.project(id ?? ""),
    enabled: Boolean(id),
    queryFn: () => api<ProjectDetail>(`/api/projects/${id}`),
  });
}

export function useCreateProject() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectCreate) => api<{ projeto_id: string }>("/api/projects", { method: "POST", body }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useUpdateProject(id: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectPatch) => api<ProjectDetail>(`/api/projects/${id}`, { method: "PATCH", body }),
    onSuccess: (detail) => {
      client.setQueryData(keys.project(id), detail);
      return client.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}
