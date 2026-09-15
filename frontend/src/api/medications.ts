/**
 * Medications API hooks
 * Endpoints: /api/medications
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

export interface Medication {
  id: number;
  name: string;
  common_dosage?: string;
  notes?: string;
  created_at?: string;
}

export interface MedicationPlan {
  id: number;
  plan_name: string;
  medication_id: number;
  medication_name?: string;
  dosage?: string;
  notes?: string;
  active: boolean;
  schedule_times: string[];
  created_at?: string;
}

export interface MedicationLog {
  id: number;
  plan_id: number;
  plan_name?: string;
  medication_name?: string;
  dosage?: string;
  taken_at: string;
  scheduled_time?: string;
  notes?: string;
  created_at?: string;
}

// Medication catalog
export const useMedications = () =>
  useQuery<Medication[]>({
    queryKey: ["medications"],
    queryFn: () => api.get("/medications/catalog"),
  });

export const useCreateMedication = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      common_dosage?: string;
      notes?: string;
    }) => api.post("/medications/catalog", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["medications"] }),
  });
};

export const useDeleteMedication = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/medications/catalog/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["medications"] }),
  });
};

// Medication plans
export const useMedicationPlans = () =>
  useQuery<MedicationPlan[]>({
    queryKey: ["medication-plans"],
    queryFn: () => api.get("/medications/plans"),
  });

export const useCreateMedicationPlan = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      plan_name: string;
      medication_id: number;
      dosage?: string;
      notes?: string;
      schedule_times: string[];
    }) => api.post("/medications/plans", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["medication-plans"] }),
  });
};

export const useDeleteMedicationPlan = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/medications/plans/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["medication-plans"] });
      qc.invalidateQueries({ queryKey: ["medication-logs"] });
    },
  });
};

// Medication logs
export const useMedicationLogs = () =>
  useQuery<MedicationLog[]>({
    queryKey: ["medication-logs"],
    queryFn: () => api.get("/medications/logs"),
  });

export const useLogMedication = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      plan_id: number;
      taken_at?: string;
      scheduled_time?: string;
      notes?: string;
    }) => api.post<MedicationLog>("/medications/logs", data),
    onSuccess: (log) => {
      qc.setQueryData<MedicationLog[]>(["medication-logs"], (current = []) => [
        log,
        ...current.filter((item) => item.id !== log.id),
      ]);
      qc.invalidateQueries({ queryKey: ["medication-logs"] });
    },
  });
};
