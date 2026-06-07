export type ReviewType = 'mr' | 'push' | 'all';

export interface ReviewItem {
  type: 'mr' | 'push';
  project_name: string;
  author: string;
  source_branch: string | null;
  target_branch: string | null;
  branch: string | null;
  updated_at: number;
  commit_messages: string;
  score: number | null;
  url: string | null;
  review_result: string;
  additions: number;
  deletions: number;
}

export interface ProjectCount {
  project_name: string;
  count: number;
}

export interface ProjectScore {
  project_name: string;
  average_score: number;
}

export interface PreviousPeriod {
  total_reviews: number;
  average_score: number;
  active_projects: number;
  active_members: number;
  deltas: {
    total_reviews_pct: number;
    average_score_diff: number;
    active_projects_diff: number;
    active_members_diff: number;
  };
}

export interface DashboardSummary {
  total_reviews: number;
  average_score: number;
  active_projects: number;
  active_members: number;
  project_counts: ProjectCount[];
  project_scores: ProjectScore[];
  recent_reviews: ReviewItem[];
  previous: PreviousPeriod | null;
}

export interface ReviewListResponse {
  items: ReviewItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface FilterOptions {
  authors: string[];
  project_names: string[];
}

export interface MemberItem {
  author: string;
  review_count: number;
  average_score: number;
  additions: number;
  deletions: number;
  active_projects: number;
}

export interface MembersResponse {
  items: MemberItem[];
  summary: {
    total_reviews: number;
    team_average_score: number;
    total_additions: number;
    total_deletions: number;
    active_members: number;
  };
}

export interface ReviewQuery {
  type?: ReviewType;
  start?: string;
  end?: string;
  author?: string;
  project_name?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}
