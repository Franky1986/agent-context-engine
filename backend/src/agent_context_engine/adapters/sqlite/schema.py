from __future__ import annotations

import sqlite3


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists sessions (
          session_id text primary key,
          client_type text not null,
          client_version text,
          thread_name text,
          session_brief text,
          project_id text,
          cwd text,
          last_workdir text,
          transcript_path text,
          started_at text,
          last_event_at text,
          ended_at text,
          status text not null default 'open',
          summary_status text not null default 'summary_pending',
          dream_status text not null default 'dream_pending',
          last_event_seq integer not null default 0,
          last_summary_event_seq integer not null default 0,
          last_dream_event_seq integer not null default 0,
          last_summary_at text,
          last_dream_at text,
          last_dream_run_id text,
          resume_count integer not null default 0,
          last_resume_at text,
          native_resume_command text,
          preferred_dream_runner text,
          dream_runner_used text,
          dream_runner_status text
        );

        create table if not exists events (
          id integer primary key autoincrement,
          session_id text not null,
          seq integer not null,
          event_name text not null,
          recorded_at text not null,
          client_type text not null,
          cwd text,
          project_id text,
          turn_id text,
          tool_name text,
          tool_use_id text,
          prompt text,
          tool_input_json text,
          tool_response_text text,
          last_assistant_message text,
          transcript_path text,
          source_id text,
          payload_json text not null,
          unique(session_id, seq),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists summaries (
          session_id text primary key,
          summary_path text not null,
          created_at text not null,
          input_event_seq_to integer not null,
          input_event_count integer not null,
          summary_kind text not null default 'deterministic_handover',
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists tool_calls (
          tool_call_id text primary key,
          session_id text not null,
          seq integer not null,
          recorded_at text not null,
          client_type text not null,
          project_id text,
          tool_name text,
          tool_use_id text,
          status text not null,
          input_json text,
          output_id text,
          created_at text not null,
          unique(session_id, seq),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists tool_outputs (
          tool_output_id text primary key,
          tool_call_id text not null,
          session_id text not null,
          seq integer not null,
          tool_use_id text,
          storage_kind text not null default 'sqlite',
          content_text text,
          path text,
          sha256 text not null,
          byte_count integer not null,
          char_count integer not null,
          line_count integer not null,
          status text not null,
          created_at text not null,
          foreign key(tool_call_id) references tool_calls(tool_call_id),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists file_accesses (
          file_access_id text primary key,
          session_id text not null,
          seq integer not null,
          recorded_at text not null,
          client_type text not null,
          project_id text,
          tool_name text,
          tool_use_id text,
          operation text not null,
          path_raw text not null,
          path_abs text,
          path_key text not null,
          source_kind text not null,
          confidence real not null,
          status text not null,
          evidence_quote text,
          created_at text not null,
          unique(session_id, seq, operation, path_key, source_kind),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists dream_runs (
          dream_run_id text primary key,
          session_id text not null,
          client_type text not null,
          runner text not null,
          runner_version text,
          runner_model text,
          started_at text not null,
          finished_at text,
          status text not null,
          input_event_seq_from integer not null,
          input_event_seq_to integer not null,
          input_event_count integer not null,
          input_transcript_path text,
          input_transcript_mtime text,
          output_summary_path text,
          output_memory_paths_json text,
          intent text,
          helpful_score real,
          tags_json text,
          error_message text,
          pipeline_version integer not null default 1,
          pipeline_status text,
          failed_stage text,
          retry_of_dream_run_id text,
          auto_retry_allowed integer not null default 1,
          created_by text not null,
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists dream_stage_runs (
          stage_run_id text primary key,
          dream_run_id text not null,
          session_id text,
          stage_name text not null,
          stage_order integer not null,
          runner text,
          model text,
          status text not null,
          started_at text not null,
          finished_at text,
          duration_ms integer,
          input_event_seq_from integer,
          input_event_seq_to integer,
          prompt_path text,
          raw_output_path text,
          parsed_output_path text,
          artifact_path text,
          metadata_json text not null default '{}',
          validation_json text not null default '{}',
          error_message text,
          prompt_tokens integer,
          cached_prompt_tokens integer,
          completion_tokens integer,
          reasoning_tokens integer,
          total_tokens integer,
          created_by text,
          foreign key(dream_run_id) references dream_runs(dream_run_id),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists semantic_proposals (
          semantic_proposal_id text primary key,
          dream_run_id text not null,
          stage_run_id text,
          session_id text,
          proposal_kind text not null,
          proposed_type text not null,
          proposed_key text,
          proposed_name text not null,
          aliases_json text not null default '[]',
          properties_json text not null default '{}',
          evidence_json text not null default '[]',
          confidence real,
          risk_level text not null default 'low',
          sensitivity text not null default 'normal',
          injection_policy text not null default 'on_demand',
          poisoning_flags_json text not null default '[]',
          status text not null default 'proposed',
          validation_json text not null default '{}',
          created_at text not null,
          updated_at text not null,
          foreign key(dream_run_id) references dream_runs(dream_run_id),
          foreign key(stage_run_id) references dream_stage_runs(stage_run_id),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists semantic_candidate_matches (
          candidate_match_id text primary key,
          semantic_proposal_id text not null,
          source text not null,
          candidate_type text not null,
          candidate_key text not null,
          candidate_name text,
          score real,
          match_reason text,
          properties_json text not null default '{}',
          evidence_json text not null default '[]',
          created_at text not null,
          foreign key(semantic_proposal_id) references semantic_proposals(semantic_proposal_id)
        );

        create table if not exists reconciliation_decisions (
          reconciliation_decision_id text primary key,
          dream_run_id text not null,
          stage_run_id text,
          semantic_proposal_id text,
          decision text not null,
          target_type text,
          target_key text,
          canonical_name text,
          aliases_json text not null default '[]',
          relation_json text not null default '{}',
          confidence real,
          reason text,
          evidence_json text not null default '[]',
          status text not null default 'pending',
          applied_at text,
          created_at text not null,
          updated_at text not null,
          foreign key(dream_run_id) references dream_runs(dream_run_id),
          foreign key(stage_run_id) references dream_stage_runs(stage_run_id),
          foreign key(semantic_proposal_id) references semantic_proposals(semantic_proposal_id)
        );

        create table if not exists dream_artifacts (
          dream_artifact_id text primary key,
          dream_run_id text not null,
          stage_run_id text,
          session_id text,
          artifact_kind text not null,
          artifact_role text not null,
          path text not null,
          sha256 text,
          byte_count integer not null default 0,
          char_count integer not null default 0,
          created_at text not null,
          metadata_json text not null default '{}',
          foreign key(dream_run_id) references dream_runs(dream_run_id),
          foreign key(stage_run_id) references dream_stage_runs(stage_run_id),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists dream_audit_entries (
          audit_entry_id text primary key,
          dream_run_id text not null,
          stage_run_id text,
          session_id text,
          entry_kind text not null,
          title text not null,
          summary text not null,
          details_json text not null default '{}',
          path text,
          created_at text not null,
          foreign key(dream_run_id) references dream_runs(dream_run_id),
          foreign key(stage_run_id) references dream_stage_runs(stage_run_id),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists semantic_entities (
          semantic_entity_id text primary key,
          entity_key text not null,
          entity_type text not null,
          name text not null,
          aliases_json text not null default '[]',
          summary text,
          properties_json text not null default '{}',
          confidence real,
          source_session_id text,
          source_dream_run_id text,
          evidence_json text not null default '[]',
          status text not null default 'active',
          created_at text not null,
          updated_at text not null,
          unique(entity_type, entity_key),
          foreign key(source_session_id) references sessions(session_id),
          foreign key(source_dream_run_id) references dream_runs(dream_run_id)
        );

        create table if not exists semantic_relations (
          semantic_relation_id text primary key,
          relation_key text not null unique,
          relation_type text not null,
          source_entity_key text not null,
          target_entity_key text not null,
          summary text,
          properties_json text not null default '{}',
          confidence real,
          source_session_id text,
          source_dream_run_id text,
          evidence_json text not null default '[]',
          status text not null default 'active',
          created_at text not null,
          updated_at text not null,
          foreign key(source_session_id) references sessions(session_id),
          foreign key(source_dream_run_id) references dream_runs(dream_run_id)
        );

        create table if not exists semantic_projection_mutations (
          mutation_id text primary key,
          dream_run_id text not null,
          reconciliation_decision_id text,
          target_kind text not null,
          target_id text,
          target_key text not null,
          mutation_kind text not null,
          mutation_summary text,
          before_snapshot_json text,
          after_snapshot_json text,
          created_at text not null,
          source_dream_run_id text,
          source_session_id text,
          foreign key(dream_run_id) references dream_runs(dream_run_id),
          foreign key(reconciliation_decision_id) references reconciliation_decisions(reconciliation_decision_id),
          foreign key(source_dream_run_id) references dream_runs(dream_run_id),
          foreign key(source_session_id) references sessions(session_id)
        );

        create table if not exists normalization_rules (
          rule_id text primary key,
          rule_kind text not null,
          target_kind text not null default 'entity',
          target_type text not null,
          canonical_value text not null,
          aliases_json text not null default '[]',
          pattern_json text not null default '{}',
          confidence real,
          status text not null default 'candidate',
          current_rollout_state text not null default 'candidate',
          source_proposal_id text,
          created_at text not null,
          updated_at text not null
        );

        create table if not exists normalization_rule_versions (
          version_id text primary key,
          rule_id text not null,
          source_proposal_id text,
          rollout_state text not null,
          version_number integer not null default 1,
          definition_json text not null default '{}',
          created_at text not null,
          foreign key(rule_id) references normalization_rules(rule_id),
          foreign key(source_proposal_id) references normalization_rule_proposals(proposal_id)
        );

        create table if not exists normalization_rule_proposals (
          proposal_id text primary key,
          dream_run_id text,
          session_id text,
          rule_kind text not null,
          target_kind text not null default 'entity',
          target_type text not null,
          canonical_value text not null,
          aliases_json text not null default '[]',
          rationale text,
          evidence_json text not null default '[]',
          status text not null default 'proposed',
          created_at text not null,
          updated_at text not null,
          foreign key(dream_run_id) references dream_runs(dream_run_id),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists normalization_rule_examples (
          example_id text primary key,
          proposal_id text not null,
          example_kind text not null default 'positive',
          source_name text,
          aliases_json text not null default '[]',
          canonical_value text,
          source_session_id text,
          source_dream_run_id text,
          metadata_json text not null default '{}',
          created_at text not null,
          foreign key(proposal_id) references normalization_rule_proposals(proposal_id),
          foreign key(source_session_id) references sessions(session_id),
          foreign key(source_dream_run_id) references dream_runs(dream_run_id)
        );

        create table if not exists normalization_rule_evaluations (
          evaluation_id text primary key,
          proposal_id text not null,
          evaluator text not null,
          corpus_size integer not null default 0,
          metrics_json text not null default '{}',
          status text not null default 'evaluated',
          created_at text not null,
          foreign key(proposal_id) references normalization_rule_proposals(proposal_id)
        );

        create table if not exists normalization_rule_reviews (
          review_id text primary key,
          proposal_id text not null,
          evaluation_id text,
          reviewer text not null,
          decision text not null,
          rationale text,
          details_json text not null default '{}',
          created_at text not null,
          foreign key(proposal_id) references normalization_rule_proposals(proposal_id),
          foreign key(evaluation_id) references normalization_rule_evaluations(evaluation_id)
        );

        create table if not exists normalization_rule_rollouts (
          rollout_id text primary key,
          rule_id text not null,
          proposal_id text,
          review_id text,
          state text not null,
          reason text,
          created_at text not null,
          foreign key(rule_id) references normalization_rules(rule_id),
          foreign key(proposal_id) references normalization_rule_proposals(proposal_id),
          foreign key(review_id) references normalization_rule_reviews(review_id)
        );

        create table if not exists operational_facts (
          operational_fact_id text primary key,
          session_id text not null,
          dream_run_id text,
          event_seq integer,
          fact_kind text not null,
          fact_key text not null,
          operation text,
          subject text,
          status text not null default 'observed',
          properties_json text not null default '{}',
          evidence_json text not null default '[]',
          created_at text not null,
          unique(session_id, dream_run_id, event_seq, fact_kind, fact_key),
          foreign key(session_id) references sessions(session_id),
          foreign key(dream_run_id) references dream_runs(dream_run_id)
        );

        create table if not exists pretool_audit_refs (
          pretool_audit_ref_id text primary key,
          session_id text not null,
          dream_run_id text,
          event_seq integer not null,
          tool_call_id text,
          tool_name text,
          tool_use_id text,
          risk_event_id text,
          status text not null,
          decision text,
          approval_state text,
          command_hash text,
          redacted_preview text,
          created_at text not null,
          unique(session_id, event_seq, tool_use_id),
          foreign key(session_id) references sessions(session_id),
          foreign key(dream_run_id) references dream_runs(dream_run_id),
          foreign key(risk_event_id) references risk_events(risk_event_id)
        );

        create table if not exists schema_reviews (
          schema_review_id text primary key,
          proposal_id text not null,
          status text not null,
          reviewer text,
          reason text,
          created_at text not null,
          reviewed_at text,
          metadata_json text not null default '{}',
          foreign key(proposal_id) references schema_proposals(proposal_id)
        );

        create table if not exists pipeline_evaluations (
          pipeline_evaluation_id text primary key,
          dream_run_id text,
          fixture_name text,
          started_at text not null,
          finished_at text,
          status text not null,
          report_path text,
          metrics_json text not null default '{}',
          error_message text,
          foreign key(dream_run_id) references dream_runs(dream_run_id)
        );

        create table if not exists projection_sync_runs (
          projection_sync_run_id text primary key,
          projection text not null,
          started_at text not null,
          finished_at text,
          status text not null,
          source_state_json text not null default '{}',
          result_json text not null default '{}',
          error_message text
        );

        create table if not exists token_usage (
          id integer primary key autoincrement,
          session_id text not null,
          turn_id text,
          recorded_at text not null,
          input_tokens integer,
          cached_input_tokens integer,
          output_tokens integer,
          reasoning_output_tokens integer,
          total_tokens integer,
          model_context_window integer,
          raw_json text not null,
          unique(session_id, turn_id, recorded_at),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists turn_metrics (
          session_id text not null,
          turn_id text not null,
          started_at text,
          completed_at text,
          duration_ms integer,
          time_to_first_token_ms integer,
          last_agent_message text,
          raw_started_json text,
          raw_complete_json text,
          primary key(session_id, turn_id),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists summary_windows (
          window_id text primary key,
          client_type text,
          project_id text,
          window_start text not null,
          window_end text not null,
          grace_until text not null,
          status text not null,
          created_at text not null,
          input_event_count integer not null,
          output_path text,
          notes text
        );

        create table if not exists scheduler_runs (
          scheduler_run_id text primary key,
          label text not null,
          started_at text not null,
          finished_at text,
          status text not null,
          exit_code integer,
          grace_minutes integer not null,
          runner text not null,
          runner_timeout integer not null,
          cwd text,
          pid integer,
          before_counts_json text not null,
          after_counts_json text,
          notes text
        );

        create table if not exists scheduler_steps (
          id integer primary key autoincrement,
          scheduler_run_id text not null,
          step_name text not null,
          started_at text not null,
          finished_at text,
          status text not null,
          exit_code integer,
          before_counts_json text not null,
          after_counts_json text,
          error_message text,
          foreign key(scheduler_run_id) references scheduler_runs(scheduler_run_id)
        );

        create table if not exists graph_artifacts (
          graph_artifact_id text primary key,
          session_id text,
          dream_run_id text,
          artifact_type text not null,
          path text not null,
          created_at text not null,
          status text not null,
          entity_count integer not null default 0,
          relation_count integer not null default 0,
          evidence_count integer not null default 0,
          runner text,
          source_paths_json text,
          intent text,
          helpful_score real,
          tags_json text,
          error_message text,
          foreign key(session_id) references sessions(session_id),
          foreign key(dream_run_id) references dream_runs(dream_run_id)
        );

        create table if not exists neo4j_imports (
          import_id text primary key,
          graph_artifact_id text,
          source_patch text not null,
          uri text not null,
          database_name text not null,
          user_name text not null,
          started_at text not null,
          finished_at text,
          status text not null,
          entity_count integer not null default 0,
          relation_count integer not null default 0,
          evidence_count integer not null default 0,
          audit_path text,
          error_message text,
          foreign key(graph_artifact_id) references graph_artifacts(graph_artifact_id)
        );

        create table if not exists memory_documents (
          document_id text primary key,
          kind text not null,
          session_id text,
          dream_run_id text,
          project_id text,
          path text not null,
          title text,
          created_at text not null,
          updated_at text not null,
          intent text,
          helpful_score real,
          tags_json text,
          memory_kind text,
          source_kind text,
          confidence real,
          risk_level text not null default 'unknown',
          sensitivity text not null default 'normal',
          injection_policy text not null default 'on_demand',
          valid_from text,
          valid_to text,
          staleness text,
          poisoning_flags_json text,
          evidence_json text,
          token_estimate integer not null default 0
        );

        create table if not exists memory_chunks (
          chunk_id text primary key,
          document_id text not null,
          chunk_index integer not null,
          kind text not null,
          session_id text,
          dream_run_id text,
          project_id text,
          path text not null,
          heading text,
          text text not null,
          tags_json text,
          memory_kind text,
          source_kind text,
          confidence real,
          risk_level text,
          sensitivity text,
          injection_policy text,
          poisoning_flags_json text,
          token_estimate integer not null default 0,
          created_at text not null,
          foreign key(document_id) references memory_documents(document_id) on delete cascade
        );

        create table if not exists memory_metadata (
          memory_id text primary key,
          target_table text not null,
          target_id text not null,
          memory_kind text not null,
          source_kind text not null,
          scope text,
          confidence real,
          risk_level text not null default 'unknown',
          sensitivity text not null default 'normal',
          injection_policy text not null default 'on_demand',
          valid_from text,
          valid_to text,
          staleness text,
          poisoning_flags_json text,
          evidence_json text,
          created_at text not null,
          updated_at text not null,
          unique(target_table, target_id)
        );

        create table if not exists retrieval_runs (
          retrieval_run_id text primary key,
          query text not null,
          rewritten_query text,
          runner text,
          client_type text,
          project_id text,
          workdir text,
          filters_json text not null default '{}',
          started_at text not null,
          finished_at text,
          status text not null,
          result_count integer not null default 0,
          error_message text
        );

        create table if not exists retrieval_results (
          retrieval_run_id text not null,
          rank integer not null,
          result_kind text not null,
          result_id text not null,
          title text,
          path text,
          score real not null default 0,
          score_breakdown_json text not null default '{}',
          provenance_json text not null default '{}',
          risk_json text not null default '{}',
          evidence_json text not null default '[]',
          injected integer not null default 0,
          created_at text not null,
          primary key(retrieval_run_id, rank),
          foreign key(retrieval_run_id) references retrieval_runs(retrieval_run_id) on delete cascade
        );

        create table if not exists memory_access_log (
          access_id integer primary key autoincrement,
          accessed_at text not null,
          access_kind text not null,
          actor text,
          runner text,
          client_type text,
          retrieval_run_id text,
          target_kind text not null,
          target_id text not null,
          project_id text,
          workdir text,
          used_in_context integer not null default 0,
          feedback text,
          notes text,
          foreign key(retrieval_run_id) references retrieval_runs(retrieval_run_id)
        );

        create table if not exists risk_events (
          risk_event_id text primary key,
          created_at text not null,
          updated_at text not null,
          client_type text,
          session_id text,
          event_seq integer,
          tool_call_id text,
          tool_name text,
          source_kind text not null,
          source_ref text,
          workdir text,
          status text not null,
          decision text not null,
          policy text not null,
          risk_level text not null,
          sensitivity text not null default 'normal',
          categories_json text not null default '[]',
          poisoning_flags_json text not null default '[]',
          injection_policy text not null default 'on_demand',
          memory_action text not null default 'reference_only',
          impact text not null default '',
          reason text not null default '',
          confidence real not null default 0,
          deterministic_flags_json text not null default '[]',
          classifier_run_id text,
          preview text,
          evidence_json text not null default '[]',
          approval_state text,
          approval_token text,
          command_hash text,
          taint_context_json text
        );

        create table if not exists risk_evidence (
          evidence_id text primary key,
          risk_event_id text not null,
          created_at text not null,
          source_kind text not null,
          source_ref text,
          field text,
          quote text,
          sha256 text,
          foreign key(risk_event_id) references risk_events(risk_event_id) on delete cascade
        );

        create table if not exists risk_policy_overrides (
          override_id text primary key,
          risk_event_id text not null,
          created_at text not null,
          reviewer text,
          action text not null,
          previous_decision text,
          new_decision text,
          previous_risk_level text,
          new_risk_level text,
          reason text not null,
          foreign key(risk_event_id) references risk_events(risk_event_id)
        );

        create table if not exists session_approved_workdirs (
          session_id text not null,
          approved_path text not null,
          created_at text not null,
          reviewer text,
          reason text not null default 'approved by user prompt',
          primary key(session_id, approved_path),
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists session_taint_resets (
          reset_id text primary key,
          session_id text not null,
          event_seq integer not null,
          created_at text not null,
          reviewer text,
          reason text not null default 'reset by user prompt',
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists classifier_runs (
          run_id text primary key,
          created_at text not null,
          finished_at text,
          client_type text,
          runner text,
          model text,
          purpose text,
          stage text not null,
          source_kind text not null,
          source_ref text,
          session_id text,
          event_seq integer,
          tool_call_id text,
          input_chars integer not null default 0,
          input_hash text,
          payload_marker text,
          prompt_tokens integer,
          completion_tokens integer,
          total_tokens integer,
          duration_ms integer,
          status text not null,
          error text,
          schema_version text not null,
          prompt_preview text,
          output_text text
        );

        create table if not exists classifier_results (
          run_id text primary key,
          created_at text not null,
          decision text not null,
          risk_level text not null,
          sensitivity text not null,
          categories_json text not null default '[]',
          poisoning_flags_json text not null default '[]',
          injection_policy text not null,
          impact text not null,
          memory_action text not null,
          reason text not null,
          confidence real not null,
          result_json text not null,
          foreign key(run_id) references classifier_runs(run_id) on delete cascade
        );

        create table if not exists classifier_feedback (
          feedback_id text primary key,
          run_id text not null,
          created_at text not null,
          reviewer text,
          verdict text not null,
          corrected_decision text,
          corrected_risk_level text,
          note text,
          foreign key(run_id) references classifier_runs(run_id)
        );

        create table if not exists firewall_state (
          id integer primary key check (id = 1),
          enabled integer not null default 1,
          updated_at text not null,
          updated_by text,
          reason text,
          disabled_until text,
          source text
        );

        create table if not exists firewall_audit (
          audit_id text primary key,
          created_at text not null,
          actor text,
          action text not null,
          previous_enabled integer,
          new_enabled integer not null,
          reason text,
          disabled_until text,
          source text
        );

        create table if not exists firewall_overrides (
          override_id text primary key,
          created_at text not null,
          updated_at text not null,
          expires_at text not null,
          enabled integer not null default 1,
          scope_type text not null,
          session_id text,
          client_type text,
          agent_name text,
          thread_name text,
          project_id text,
          workdir text,
          reason text not null,
          created_by text not null,
          source text not null
        );

        create table if not exists firewall_override_audit (
          audit_id text primary key,
          override_id text,
          created_at text not null,
          action text not null,
          actor text not null,
          reason text,
          foreign key(override_id) references firewall_overrides(override_id)
        );

        create table if not exists firewall_rules (
          rule_id text primary key,
          family_id text,
          version integer not null default 1,
          supersedes_rule_id text,
          rule_kind text not null default 'deterministic',
          created_at text not null,
          updated_at text not null,
          status text not null default 'active',
          name text not null,
          description text,
          scope_type text not null default 'global',
          project_id text,
          workdir_prefix text,
          session_id text,
          allowed_tools_json text not null default '[]',
          allowed_actions_json text not null default '[]',
          denied_actions_json text not null default '[]',
          allowed_hosts_json text not null default '[]',
          allowed_local_paths_json text not null default '[]',
          allowed_remote_paths_json text not null default '[]',
          command_patterns_json text not null default '[]',
          max_risk_level text,
          expires_at text,
          permanent integer not null default 0,
          created_by text not null,
          created_from_session_id text,
          created_from_event_seq integer,
          source_line text not null,
          reason text not null,
          policy_text text,
          policy_text_sanitized text,
          classifier_context text,
          context_hash text,
          rule_json text not null default '{}'
        );

        create table if not exists firewall_rule_audit (
          audit_id text primary key,
          rule_id text,
          family_id text,
          created_at text not null,
          action text not null,
          actor text not null,
          reason text,
          before_json text,
          after_json text,
          risk_event_id text,
          session_id text,
          event_seq integer,
          foreign key(rule_id) references firewall_rules(rule_id)
        );

        create table if not exists firewall_rule_suggestions (
          suggestion_id text primary key,
          created_at text not null,
          status text not null default 'draft',
          source_window_start text,
          source_window_end text,
          source_filters_json text not null default '{}',
          summary_json text not null default '{}',
          suggested_command text not null,
          safety_notes_json text not null default '[]',
          redaction_report_json text not null default '{}'
        );

        create table if not exists firewall_rule_suggestion_evidence (
          evidence_id text primary key,
          suggestion_id text not null,
          source_kind text not null,
          source_id text,
          trusted_level text not null,
          raw_payload_included integer not null default 0,
          tainted_source integer not null default 0,
          allowed_for_policy_generation integer not null default 1,
          summary_json text not null default '{}',
          foreign key(suggestion_id) references firewall_rule_suggestions(suggestion_id)
        );

        create table if not exists firewall_intent_approvals (
          intent_id text primary key,
          created_at text not null,
          expires_at text not null,
          session_id text,
          user_event_seq integer,
          intent_text text not null,
          allowed_hosts_json text not null default '[]',
          allowed_actions_json text not null default '[]',
          allowed_paths_json text not null default '[]',
          constraints_json text not null default '{}',
          source_user_message_hash text
        );

        create table if not exists firewall_session_scopes (
          session_id text not null,
          scope_path text not null,
          created_at text not null,
          updated_at text not null,
          source text not null,
          reason text,
          event_seq integer,
          primary key(session_id, scope_path)
        );

        create virtual table if not exists memory_chunks_fts using fts5(
          chunk_id unindexed,
          document_id unindexed,
          project_id unindexed,
          kind unindexed,
          heading,
          text,
          tags
        );

        create table if not exists dream_tags (
          dream_run_id text not null,
          tag text not null,
          primary key(dream_run_id, tag),
          foreign key(dream_run_id) references dream_runs(dream_run_id)
        );

        create table if not exists graph_entities (
          entity_id text primary key,
          type text not null,
          key text not null,
          name text not null,
          aliases_json text,
          properties_json text,
          confidence real,
          first_seen_at text not null,
          last_seen_at text not null,
          artifact_id text,
          session_id text,
          dream_run_id text,
          intent text,
          helpful_score real,
          tags_json text,
          memory_kind text,
          source_kind text,
          risk_level text,
          sensitivity text,
          injection_policy text,
          valid_from text,
          valid_to text,
          staleness text,
          poisoning_flags_json text,
          evidence_json text,
          unique(type, key)
        );

        create table if not exists graph_relations (
          relation_id text primary key,
          from_entity_id text not null,
          relation_type text not null,
          to_entity_id text not null,
          properties_json text,
          confidence real,
          first_seen_at text not null,
          last_seen_at text not null,
          artifact_id text,
          session_id text,
          dream_run_id text,
          intent text,
          helpful_score real,
          tags_json text,
          memory_kind text,
          source_kind text,
          risk_level text,
          sensitivity text,
          injection_policy text,
          valid_from text,
          valid_to text,
          staleness text,
          poisoning_flags_json text,
          evidence_json text,
          unique(from_entity_id, relation_type, to_entity_id)
        );

        create table if not exists graph_evidence (
          evidence_id text primary key,
          owner_type text not null,
          owner_id text not null,
          source_type text,
          session_id text,
          event_seq integer,
          field text,
          path text,
          quote text
        );

        create table if not exists schema_proposals (
          proposal_id text primary key,
          kind text not null,
          proposed_name text not null,
          canonical_name text,
          status text not null,
          confidence real,
          reason text,
          examples_json text not null default '[]',
          evidence_json text not null default '[]',
          review_json text not null default '{}',
          proposed_by text,
          source_session_id text,
          source_dream_run_id text,
          source_graph_artifact_id text,
          created_at text not null,
          updated_at text not null,
          reviewed_at text,
          reviewer text,
          decision_reason text
        );

        create table if not exists schema_proposal_audit (
          audit_id text primary key,
          proposal_id text not null,
          action text not null,
          actor text,
          reason text,
          before_json text,
          after_json text,
          created_at text not null,
          foreign key(proposal_id) references schema_proposals(proposal_id)
        );

        create table if not exists graph_schema_registry (
          schema_item_id text primary key,
          kind text not null,
          name text not null,
          status text not null,
          canonical_name text,
          created_from_proposal_id text,
          reason text,
          created_at text not null,
          updated_at text not null,
          unique(kind, name),
          foreign key(created_from_proposal_id) references schema_proposals(proposal_id)
        );

        create table if not exists dream_queue (
          dream_queue_id text primary key,
          session_id text not null,
          reason text not null,
          runner text not null,
          runner_model text,
          runner_timeout integer not null,
          status text not null,
          priority integer not null default 100,
          attempts integer not null default 0,
          max_attempts integer not null default 1,
          worker_pid integer,
          created_at text not null,
          updated_at text not null,
          started_at text,
          finished_at text,
          lease_until text,
          locked_by text,
          retry_of_dream_run_id text,
          pipeline_version integer not null default 1,
          last_error text,
          created_by text,
          foreign key(session_id) references sessions(session_id)
        );

        create table if not exists hook_queue_audit (
          event_id text primary key,
          session_id text not null,
          reserved_seq integer not null,
          client_type text not null,
          event_name text not null,
          hook_mode text not null default 'queue',
          recorded_at text not null,
          queued_at text not null,
          processed_at text,
          status text not null default 'queued',
          synchronous_decision text,
          error text,
          foreign key(session_id) references sessions(session_id)
        );
        """
    )
    ensure_column(conn, "sessions", "thread_name", "text")
    ensure_column(conn, "sessions", "session_brief", "text")
    ensure_column(conn, "sessions", "last_workdir", "text")
    ensure_column(conn, "sessions", "last_reserved_event_seq", "integer not null default 0")
    ensure_column(conn, "dream_runs", "runner_model", "text")
    ensure_column(conn, "dream_runs", "intent", "text")
    ensure_column(conn, "dream_runs", "helpful_score", "real")
    ensure_column(conn, "dream_runs", "tags_json", "text")
    ensure_column(conn, "dream_runs", "duration_ms", "integer")
    ensure_column(conn, "dream_runs", "prompt_tokens", "integer")
    ensure_column(conn, "dream_runs", "cached_prompt_tokens", "integer")
    ensure_column(conn, "dream_runs", "completion_tokens", "integer")
    ensure_column(conn, "dream_runs", "reasoning_tokens", "integer")
    ensure_column(conn, "dream_runs", "total_tokens", "integer")
    ensure_column(conn, "dream_runs", "pipeline_version", "integer not null default 1")
    ensure_column(conn, "dream_runs", "pipeline_status", "text")
    ensure_column(conn, "dream_runs", "failed_stage", "text")
    ensure_column(conn, "dream_runs", "retry_of_dream_run_id", "text")
    ensure_column(conn, "dream_runs", "auto_retry_allowed", "integer not null default 1")
    ensure_column(conn, "dream_queue", "lease_until", "text")
    ensure_column(conn, "dream_queue", "locked_by", "text")
    ensure_column(conn, "dream_queue", "retry_of_dream_run_id", "text")
    ensure_column(conn, "dream_queue", "pipeline_version", "integer not null default 1")
    ensure_column(conn, "semantic_proposals", "schema_version", "text")
    ensure_column(conn, "semantic_proposals", "summary", "text")
    ensure_column(conn, "semantic_proposals", "review_required", "integer not null default 0")
    ensure_column(conn, "semantic_proposals", "review_reason", "text")
    ensure_column(conn, "reconciliation_decisions", "schema_version", "text")
    ensure_column(conn, "reconciliation_decisions", "human_summary", "text")
    ensure_column(conn, "reconciliation_decisions", "write_patch_json", "text")
    ensure_column(conn, "reconciliation_decisions", "review_required", "integer not null default 0")
    ensure_column(conn, "reconciliation_decisions", "review_reason", "text")
    ensure_column(conn, "graph_artifacts", "intent", "text")
    ensure_column(conn, "graph_artifacts", "helpful_score", "real")
    ensure_column(conn, "graph_artifacts", "tags_json", "text")
    ensure_column(conn, "events", "source_id", "text")
    ensure_column(conn, "risk_events", "approval_state", "text")
    ensure_column(conn, "risk_events", "approval_token", "text")
    ensure_column(conn, "risk_events", "command_hash", "text")
    ensure_column(conn, "risk_events", "taint_context_json", "text")
    ensure_column(conn, "firewall_state", "disabled_until", "text")
    ensure_column(conn, "firewall_audit", "disabled_until", "text")
    for column, ctype in {
        "agent_name": "text",
        "thread_name": "text",
        "project_id": "text",
        "workdir": "text",
    }.items():
        ensure_column(conn, "firewall_overrides", column, ctype)
    for table in ("memory_documents", "memory_chunks", "graph_entities", "graph_relations"):
        ensure_column(conn, table, "memory_kind", "text")
        ensure_column(conn, table, "source_kind", "text")
        ensure_column(conn, table, "confidence", "real")
        ensure_column(conn, table, "risk_level", "text")
        ensure_column(conn, table, "sensitivity", "text")
        ensure_column(conn, table, "injection_policy", "text")
        ensure_column(conn, table, "poisoning_flags_json", "text")
    for table in ("memory_documents", "graph_entities", "graph_relations"):
        ensure_column(conn, table, "valid_from", "text")
        ensure_column(conn, table, "valid_to", "text")
        ensure_column(conn, table, "staleness", "text")
        ensure_column(conn, table, "evidence_json", "text")
    for column, ctype in {
        "family_id": "text",
        "version": "integer not null default 1",
        "supersedes_rule_id": "text",
        "rule_kind": "text not null default 'deterministic'",
        "policy_text": "text",
        "policy_text_sanitized": "text",
        "classifier_context": "text",
        "context_hash": "text",
        "permanent": "integer not null default 0",
    }.items():
        ensure_column(conn, "firewall_rules", column, ctype)
    ensure_column(conn, "firewall_rule_audit", "family_id", "text")
    if _has_rows(conn, "select 1 from firewall_rules where family_id is null or family_id = '' limit 1"):
        conn.execute("update firewall_rules set family_id = rule_id where family_id is null or family_id = ''")
    if _has_rows(conn, "select 1 from firewall_rules where rule_kind is null or rule_kind = '' limit 1"):
        conn.execute("update firewall_rules set rule_kind = 'deterministic' where rule_kind is null or rule_kind = ''")
    if _has_rows(conn, "select 1 from firewall_rules where version is null limit 1"):
        conn.execute("update firewall_rules set version = 1 where version is null")
    if _has_rows(conn, "select 1 from firewall_rule_audit where family_id is null or family_id = '' limit 1"):
        conn.execute(
            """
            update firewall_rule_audit
            set family_id = (
              select family_id
              from firewall_rules
              where firewall_rules.rule_id = firewall_rule_audit.rule_id
            )
            where family_id is null or family_id = ''
            """
        )
    conn.executescript(
        """
        create index if not exists idx_memory_documents_project on memory_documents(project_id, kind, updated_at);
        create index if not exists idx_memory_documents_intent on memory_documents(intent, helpful_score);
        create index if not exists idx_memory_chunks_project on memory_chunks(project_id, kind, created_at);
        create index if not exists idx_memory_chunks_session on memory_chunks(session_id, dream_run_id);
        create index if not exists idx_dream_tags_tag on dream_tags(tag, dream_run_id);
        create index if not exists idx_sessions_last_event on sessions(last_event_at);
        create index if not exists idx_sessions_project_last_event on sessions(project_id, last_event_at);
        create index if not exists idx_sessions_client_last_event on sessions(client_type, last_event_at);
        create index if not exists idx_sessions_workdir_last_event on sessions(last_workdir, cwd, last_event_at);
        create index if not exists idx_sessions_pending_summary on sessions(summary_status, last_event_seq, last_summary_event_seq);
        create index if not exists idx_sessions_pending_dream on sessions(dream_status, last_event_seq, last_dream_event_seq);
        create index if not exists idx_events_session_seq on events(session_id, seq);
        create index if not exists idx_dream_runs_session_status_window on dream_runs(session_id, status, input_event_seq_from, input_event_seq_to);
        create index if not exists idx_dream_runs_session_status_id on dream_runs(session_id, status, dream_run_id);
        create index if not exists idx_dream_runs_session_started on dream_runs(session_id, started_at);
        create index if not exists idx_dream_runs_pipeline on dream_runs(pipeline_version, pipeline_status, status);
        create index if not exists idx_dream_stage_runs_dream on dream_stage_runs(dream_run_id, stage_order);
        create index if not exists idx_dream_stage_runs_status on dream_stage_runs(status, stage_name, started_at);
        create index if not exists idx_semantic_proposals_dream on semantic_proposals(dream_run_id, proposal_kind, status);
        create index if not exists idx_semantic_proposals_type_name on semantic_proposals(proposed_type, proposed_name);
        create index if not exists idx_semantic_candidate_matches_proposal on semantic_candidate_matches(semantic_proposal_id, score);
        create index if not exists idx_reconciliation_decisions_dream on reconciliation_decisions(dream_run_id, decision, status);
        create index if not exists idx_dream_artifacts_dream on dream_artifacts(dream_run_id, artifact_role);
        create index if not exists idx_dream_audit_entries_dream on dream_audit_entries(dream_run_id, entry_kind);
        create index if not exists idx_semantic_entities_key on semantic_entities(entity_type, entity_key);
        create index if not exists idx_semantic_entities_source on semantic_entities(source_dream_run_id, source_session_id);
        create index if not exists idx_semantic_relations_key on semantic_relations(relation_type, source_entity_key, target_entity_key);
        create index if not exists idx_semantic_projection_mutations_dream on semantic_projection_mutations(dream_run_id, target_kind, created_at);
        create index if not exists idx_semantic_projection_mutations_decision on semantic_projection_mutations(reconciliation_decision_id, target_kind, created_at);
        create index if not exists idx_semantic_projection_mutations_target on semantic_projection_mutations(target_id, target_key);
        create index if not exists idx_normalization_rules_kind_state on normalization_rules(rule_kind, target_type, current_rollout_state);
        create index if not exists idx_normalization_rule_proposals_dream on normalization_rule_proposals(dream_run_id, status, created_at);
        create index if not exists idx_normalization_rule_examples_proposal on normalization_rule_examples(proposal_id, example_kind);
        create index if not exists idx_normalization_rule_evaluations_proposal on normalization_rule_evaluations(proposal_id, created_at);
        create index if not exists idx_normalization_rule_reviews_proposal on normalization_rule_reviews(proposal_id, decision, created_at);
        create index if not exists idx_normalization_rule_rollouts_rule on normalization_rule_rollouts(rule_id, state, created_at);
        create index if not exists idx_operational_facts_session on operational_facts(session_id, dream_run_id, event_seq);
        create index if not exists idx_operational_facts_kind on operational_facts(fact_kind, fact_key);
        create index if not exists idx_pretool_audit_refs_session on pretool_audit_refs(session_id, event_seq);
        create index if not exists idx_schema_reviews_proposal on schema_reviews(proposal_id, status);
        create index if not exists idx_pipeline_evaluations_run on pipeline_evaluations(dream_run_id, status);
        create index if not exists idx_projection_sync_runs_projection on projection_sync_runs(projection, status, started_at);
        create index if not exists idx_graph_artifacts_dream_type_status on graph_artifacts(dream_run_id, artifact_type, status);
        create index if not exists idx_graph_entities_type_name on graph_entities(type, name);
        create index if not exists idx_graph_entities_intent on graph_entities(intent, helpful_score);
        create index if not exists idx_graph_relations_from on graph_relations(from_entity_id, relation_type);
        create index if not exists idx_graph_relations_to on graph_relations(to_entity_id, relation_type);
        create index if not exists idx_graph_evidence_owner on graph_evidence(owner_type, owner_id);
        create index if not exists idx_schema_proposals_status on schema_proposals(status, updated_at);
        create index if not exists idx_schema_proposals_kind_name on schema_proposals(kind, proposed_name);
        create index if not exists idx_schema_proposal_audit_proposal on schema_proposal_audit(proposal_id, created_at);
        create index if not exists idx_graph_schema_registry_kind_name on graph_schema_registry(kind, name);
        create index if not exists idx_dream_queue_status_priority on dream_queue(status, priority, created_at);
        create index if not exists idx_dream_queue_session_status on dream_queue(session_id, status);
        create index if not exists idx_tool_calls_session on tool_calls(session_id, seq);
        create index if not exists idx_tool_outputs_session on tool_outputs(session_id, seq);
        create index if not exists idx_tool_outputs_call on tool_outputs(tool_call_id);
        create index if not exists idx_token_usage_session_turn on token_usage(session_id, turn_id);
        create index if not exists idx_file_accesses_session on file_accesses(session_id, seq);
        create index if not exists idx_file_accesses_path on file_accesses(path_key, operation, recorded_at);
        create index if not exists idx_file_accesses_operation on file_accesses(operation, recorded_at);
        create index if not exists idx_memory_metadata_target on memory_metadata(target_table, target_id);
        create index if not exists idx_memory_metadata_policy on memory_metadata(injection_policy, sensitivity, risk_level);
        create index if not exists idx_retrieval_runs_started on retrieval_runs(started_at, status);
        create index if not exists idx_retrieval_results_kind on retrieval_results(result_kind, result_id);
        create index if not exists idx_memory_access_target on memory_access_log(target_kind, target_id, accessed_at);
        create index if not exists idx_memory_access_retrieval on memory_access_log(retrieval_run_id);
        create index if not exists idx_risk_events_status on risk_events(status, risk_level, created_at);
        create index if not exists idx_risk_events_created on risk_events(created_at);
        create index if not exists idx_risk_events_session on risk_events(session_id, event_seq);
        create index if not exists idx_risk_events_client_workdir on risk_events(client_type, workdir, created_at);
        create index if not exists idx_risk_events_command_hash on risk_events(session_id, command_hash, status, created_at);
        create index if not exists idx_risk_evidence_event on risk_evidence(risk_event_id);
        create index if not exists idx_classifier_runs_stage on classifier_runs(stage, status, created_at);
        create index if not exists idx_classifier_runs_source on classifier_runs(source_kind, source_ref);
        create index if not exists idx_classifier_runs_session on classifier_runs(session_id, event_seq);
        create index if not exists idx_classifier_feedback_run on classifier_feedback(run_id);
        create index if not exists idx_firewall_rules_status on firewall_rules(status, expires_at, updated_at);
        create index if not exists idx_firewall_rules_scope on firewall_rules(scope_type, project_id, session_id, workdir_prefix);
        create index if not exists idx_firewall_rules_family on firewall_rules(family_id, version);
        create index if not exists idx_firewall_rules_kind on firewall_rules(rule_kind, status, updated_at);
        create index if not exists idx_firewall_session_scopes_session on firewall_session_scopes(session_id, updated_at);
        create index if not exists idx_firewall_rule_audit_rule on firewall_rule_audit(rule_id, created_at);
        create index if not exists idx_firewall_rule_audit_family on firewall_rule_audit(family_id, created_at);
        create index if not exists idx_firewall_rule_audit_session on firewall_rule_audit(session_id, event_seq);
        create index if not exists idx_firewall_rule_suggestions_created on firewall_rule_suggestions(created_at, status);
        create index if not exists idx_firewall_rule_suggestion_evidence on firewall_rule_suggestion_evidence(suggestion_id);
        create index if not exists idx_firewall_intent_session on firewall_intent_approvals(session_id, expires_at);
        create unique index if not exists idx_events_source_id on events(session_id, source_id) where source_id is not null;
        create index if not exists idx_hook_queue_audit_status on hook_queue_audit(status, queued_at);
        create unique index if not exists idx_hook_queue_audit_session_seq on hook_queue_audit(session_id, reserved_seq);
        """
    )
    conn.commit()



def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row["name"] for row in conn.execute(f"pragma table_info({table})")}
    if column not in existing:
        conn.execute(f"alter table {table} add column {column} {definition}")


def _has_rows(conn: sqlite3.Connection, sql: str) -> bool:
    return conn.execute(sql).fetchone() is not None
