/**
 * Gym API hooks
 * Endpoints: /api/gym/exercises, /api/gym/sets, /api/gym/history
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";

// Types
export interface Exercise {
  id: number;
  name: string;
  muscle_group: string;
  equipment?: string;
  description?: string;
}

export interface TrainingSet {
  id: number;
  name: string;
  description?: string;
  exercises: {
    id: number;
    exercise_id: number;
    exercise_name: string;
    order_index: number;
  }[];
}

export interface TrainingHistory {
  id: number;
  training_set_id: number;
  set_name: string;
  session_date: string;
  duration_minutes?: number;
  notes?: string;
  exercises: {
    exercise_name: string;
    sets_completed: number;
    reps_completed?: number;
    weight_kg?: string;
  }[];
}

export interface WorkoutExerciseInput {
  exercise_id?: number;
  exercise_name?: string;
  sets_completed?: number;
  reps_completed?: number;
  sets?: Array<Record<string, unknown>>;
}

// Exercise hooks
export const useExercises = () =>
  useQuery<Exercise[]>({
    queryKey: ["exercises"],
    queryFn: () => api.get("/gym/exercises"),
  });

export const useCreateExercise = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      muscle_group: string;
      equipment?: string;
      description?: string;
    }) => api.post("/gym/exercises", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["exercises"] }),
  });
};

export const useUpdateExercise = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      id: number;
      name: string;
      muscle_group: string;
      equipment?: string;
      description?: string;
    }) => api.put(`/gym/exercises/${data.id}`, {
      name: data.name,
      muscle_group: data.muscle_group,
      equipment: data.equipment,
      description: data.description,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["exercises"] });
      qc.invalidateQueries({ queryKey: ["training-sets"] });
    },
  });
};

export const useDeleteExercise = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/gym/exercises/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["exercises"] }),
  });
};

// Training Sets hooks
export const useTrainingSets = () =>
  useQuery<TrainingSet[]>({
    queryKey: ["training-sets"],
    queryFn: () => api.get("/gym/sets"),
  });

export const useCreateTrainingSet = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      name: string;
      description?: string;
      exercises: { exercise_id: number }[];
    }) => api.post("/gym/sets", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["training-sets"] }),
  });
};


export const useUpdateTrainingSet = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      id: number;
      name: string;
      description?: string;
      exercises: { exercise_id: number }[];
    }) => api.put(`/gym/sets/${data.id}`, {
      name: data.name,
      description: data.description,
      exercises: data.exercises,
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["training-sets"] }),
  });
};
export const useDeleteTrainingSet = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/gym/sets/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["training-sets"] }),
  });
};

// Training History hooks
export const useTrainingHistory = () =>
  useQuery<TrainingHistory[]>({
    queryKey: ["training-history"],
    queryFn: () => api.get("/gym/history"),
  });

export const useLogWorkout = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      training_set_id?: number;
      name?: string;
      session_date: string;
      duration_minutes?: number;
      notes?: string;
      exercises: WorkoutExerciseInput[];
    }) => api.post("/gym/history", data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["training-history"] }),
  });
};

export const useDeleteTrainingHistory = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/gym/history/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["training-history"] }),
  });
};
