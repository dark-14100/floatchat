/**
 * FloatChat — Authentication TypeScript Types (Feature 13)
 */

export type UserRole = "researcher" | "admin";

export interface User {
  user_id: string;
  name: string;
  email: string;
  role: UserRole;
  created_at?: string;
}

export interface SignupRequest {
  name: string;
  email: string;
  password: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface ForgotPasswordRequest {
  email: string;
}

export interface ResetPasswordRequest {
  token: string;
  new_password: string;
}

export interface AuthResponse {
  user_id: string;
  name: string;
  email: string;
  role: UserRole;
  access_token: string;
  migrated_sessions_count: number;
}

export interface RefreshResponse {
  access_token: string;
  user: User;
}

export interface MessageResponse {
  message: string;
}
