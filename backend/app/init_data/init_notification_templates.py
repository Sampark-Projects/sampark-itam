# backend/app/init_data/init_notification_templates.py
"""
Initialize default notification templates for the system.
These templates are system-wide (tenant_id = NULL).
"""
from sqlalchemy.orm import Session
from app.models import NotificationTemplate
import uuid


def init_notification_templates(db: Session):
    """Create default notification templates"""
    
    templates = [
        {
            'template_code': 'asset_review_due',
            'name': 'Asset Review Due',
            'description': 'Notification when asset review is due',
            'subject_template': 'Asset Review Due: {{asset_name}}',
            'body_template_html': '''
            <html>
            <body>
                <p>Dear {{user_name}},</p>
                <p>The following asset requires review:</p>
                <ul>
                    <li><strong>Asset:</strong> {{asset_name}}</li>
                    <li><strong>Site:</strong> {{site_name}}</li>
                    <li><strong>Last Review:</strong> {{last_review_date}}</li>
                    <li><strong>Days Until Review:</strong> {{days_until_review}}</li>
                </ul>
                <p><a href="{{asset_url}}">Review Asset</a></p>
                <p>Best regards,<br>Sampark</p>
            </body>
            </html>
            ''',
            'body_template_text': '''
            Dear {{user_name}},
            
            The following asset requires review:
            - Asset: {{asset_name}}
            - Site: {{site_name}}
            - Last Review: {{last_review_date}}
            - Days Until Review: {{days_until_review}}
            
            Review Asset: {{asset_url}}
            
            Best regards,
            Sampark
            ''',
            'variables': ['user_name', 'asset_name', 'site_name', 'last_review_date', 'days_until_review', 'asset_url']
        },
        {
            'template_code': 'asset_review_overdue',
            'name': 'Asset Review Overdue',
            'description': 'Notification when asset review is overdue',
            'subject_template': 'Asset Review Overdue: {{asset_name}}',
            'body_template_html': '''
            <html>
            <body>
                <p>Dear {{user_name}},</p>
                <p><strong>URGENT:</strong> The following asset has an overdue review:</p>
                <ul>
                    <li><strong>Asset:</strong> {{asset_name}}</li>
                    <li><strong>Site:</strong> {{site_name}}</li>
                    <li><strong>Last Review:</strong> {{last_review_date}}</li>
                    <li><strong>Days Overdue:</strong> {{days_overdue}}</li>
                </ul>
                <p><a href="{{asset_url}}">Review Asset Now</a></p>
                <p>Best regards,<br>Sampark</p>
            </body>
            </html>
            ''',
            'body_template_text': '''
            Dear {{user_name}},
            
            URGENT: The following asset has an overdue review:
            - Asset: {{asset_name}}
            - Site: {{site_name}}
            - Last Review: {{last_review_date}}
            - Days Overdue: {{days_overdue}}
            
            Review Asset Now: {{asset_url}}
            
            Best regards,
            Sampark
            ''',
            'variables': ['user_name', 'asset_name', 'site_name', 'last_review_date', 'days_overdue', 'asset_url']
        },
        {
            'template_code': 'risk_alert',
            'name': 'High Risk Alert',
            'description': 'Notification when asset has high risk score',
            'subject_template': 'High Risk Alert: {{asset_name}} (Risk Score: {{risk_score}})',
            'body_template_html': '''
            <html>
            <body>
                <p>Dear {{user_name}},</p>
                <p>The following asset has a high risk score:</p>
                <ul>
                    <li><strong>Asset:</strong> {{asset_name}}</li>
                    <li><strong>Risk Score:</strong> {{risk_score}} ({{risk_level}})</li>
                    <li><strong>Site:</strong> {{site_name}}</li>
                </ul>
                <p><a href="{{asset_url}}">View Asset Details</a></p>
                <p>Best regards,<br>Sampark</p>
            </body>
            </html>
            ''',
            'body_template_text': '''
            Dear {{user_name}},
            
            The following asset has a high risk score:
            - Asset: {{asset_name}}
            - Risk Score: {{risk_score}} ({{risk_level}})
            - Site: {{site_name}}
            
            View Asset Details: {{asset_url}}
            
            Best regards,
            Sampark
            ''',
            'variables': ['user_name', 'asset_name', 'risk_score', 'risk_level', 'site_name', 'asset_url']
        },
        {
            'template_code': 'asset_expiry_alert',
            'name': 'Asset Warranty / Support Expiry',
            'description': 'Notification when a warranty, AMC, support contract or licence is about to expire or has expired',
            'subject_template': 'Asset {{expiry_type}} {{status_text}}: {{asset_name}}',
            'body_template_html': '''
            <html>
            <body>
                <p>Dear {{user_name}},</p>
                <p>The {{expiry_type}} of the following asset {{status_text}}:</p>
                <ul>
                    <li><strong>Asset:</strong> {{asset_name}}</li>
                    <li><strong>Site:</strong> {{site_name}}</li>
                    <li><strong>Expiry date:</strong> {{expiry_date}}</li>
                </ul>
                <p><a href="{{asset_url}}">View Asset</a></p>
                <p>Best regards,<br>Sampark</p>
            </body>
            </html>
            ''',
            'body_template_text': '''
            Dear {{user_name}},

            The {{expiry_type}} of the following asset {{status_text}}:
            - Asset: {{asset_name}}
            - Site: {{site_name}}
            - Expiry date: {{expiry_date}}

            View Asset: {{asset_url}}

            Best regards,
            Sampark
            ''',
            'variables': ['user_name', 'asset_name', 'site_name', 'expiry_type', 'expiry_date', 'days_left', 'status_text', 'asset_url']
        },
        {
            'template_code': 'lifecycle_task_assigned',
            'name': 'Lifecycle Task Assigned',
            'description': 'Notification when a lifecycle workflow step is waiting for the role of the user',
            'subject_template': 'Action needed ({{workflow_name}}): {{step_name}} - {{asset_name}}',
            'body_template_html': '''
            <html>
            <body>
                <p>Dear {{user_name}},</p>
                <p>A {{step_type}} is waiting for you in the {{workflow_name}} workflow:</p>
                <ul>
                    <li><strong>Asset:</strong> {{asset_name}}</li>
                    <li><strong>Step:</strong> {{step_name}}</li>
                </ul>
                <p><a href="{{asset_url}}">Open Asset</a></p>
                <p>Best regards,<br>Sampark</p>
            </body>
            </html>
            ''',
            'body_template_text': '''
            Dear {{user_name}},

            A {{step_type}} is waiting for you in the {{workflow_name}} workflow:
            - Asset: {{asset_name}}
            - Step: {{step_name}}

            Open Asset: {{asset_url}}

            Best regards,
            Sampark
            ''',
            'variables': ['user_name', 'asset_name', 'workflow_name', 'step_name', 'step_type', 'asset_url']
        },
        {
            'template_code': 'lifecycle_run_finished',
            'name': 'Lifecycle Workflow Finished',
            'description': 'Notification to the person who started a lifecycle workflow when it is completed or rejected',
            'subject_template': '{{workflow_name}} {{result}}: {{asset_name}}',
            'body_template_html': '''
            <html>
            <body>
                <p>Dear {{user_name}},</p>
                <p>The {{workflow_name}} workflow of the following asset is {{result}}:</p>
                <ul>
                    <li><strong>Asset:</strong> {{asset_name}}</li>
                    <li><strong>Note:</strong> {{note}}</li>
                </ul>
                <p><a href="{{asset_url}}">Open Asset</a></p>
                <p>Best regards,<br>Sampark</p>
            </body>
            </html>
            ''',
            'body_template_text': '''
            Dear {{user_name}},

            The {{workflow_name}} workflow of the following asset is {{result}}:
            - Asset: {{asset_name}}
            - Note: {{note}}

            Open Asset: {{asset_url}}

            Best regards,
            Sampark
            ''',
            'variables': ['user_name', 'asset_name', 'workflow_name', 'result', 'note', 'asset_url']
        },
        {
            'template_code': 'config_alert',
            'name': 'Configuration Alert',
            'description': 'Notification when a stored configuration differs from its golden baseline or its backup is overdue',
            'subject_template': 'Configuration {{alert_title}}: {{artifact_name}} - {{asset_name}}',
            'body_template_html': '''
            <html>
            <body>
                <p>Dear {{user_name}},</p>
                <p>The configuration item <strong>{{artifact_name}}</strong> of asset <strong>{{asset_name}}</strong> needs attention:</p>
                <p>{{message}}</p>
                <p><a href="{{asset_url}}">Open Asset</a></p>
                <p>Best regards,<br>Sampark</p>
            </body>
            </html>
            ''',
            'body_template_text': '''
            Dear {{user_name}},

            The configuration item {{artifact_name}} of asset {{asset_name}} needs attention:
            {{message}}

            Open Asset: {{asset_url}}

            Best regards,
            Sampark
            ''',
            'variables': ['user_name', 'artifact_name', 'asset_name', 'alert_title', 'message', 'asset_url']
        },
        {
            'template_code': 'maintenance_overdue',
            'name': 'Maintenance Overdue',
            'description': 'Notification when a planned maintenance task is past its due date',
            'subject_template': 'Maintenance overdue: {{task_title}} - {{asset_name}}',
            'body_template_html': '''
            <html>
            <body>
                <p>Dear {{user_name}},</p>
                <p>The {{kind}} task <strong>{{task_title}}</strong> on asset <strong>{{asset_name}}</strong> was due on {{due_date}} and is {{days_overdue}} day(s) overdue.</p>
                <p><a href="{{asset_url}}">Open Asset</a></p>
                <p>Best regards,<br>Sampark</p>
            </body>
            </html>
            ''',
            'body_template_text': '''
            Dear {{user_name}},

            The {{kind}} task {{task_title}} on asset {{asset_name}} was due on {{due_date}} and is {{days_overdue}} day(s) overdue.

            Open Asset: {{asset_url}}

            Best regards,
            Sampark
            ''',
            'variables': ['user_name', 'asset_name', 'task_title', 'kind', 'due_date', 'days_overdue', 'asset_url']
        },
        {
            'template_code': 'approval_requested',
            'name': 'Approval Requested',
            'description': 'Notification to approvers when a purchase request waits for a decision',
            'subject_template': '{{item_type}} {{item_code}} needs your approval: {{title}}',
            'body_template_html': '''
            <html>
            <body>
                <p>Dear {{user_name}},</p>
                <p>{{requester_name}} submitted <strong>{{item_type}} {{item_code}}</strong> ({{title}}) and it waits for a decision.</p>
                <p>{{message}}</p>
                <p><a href="{{item_url}}">Open</a></p>
                <p>Best regards,<br>Sampark</p>
            </body>
            </html>
            ''',
            'body_template_text': '''
            Dear {{user_name}},

            {{requester_name}} submitted {{item_type}} {{item_code}} ({{title}}) and it waits for a decision.
            {{message}}

            Open: {{item_url}}

            Best regards,
            Sampark
            ''',
            'variables': ['user_name', 'item_type', 'item_code', 'title', 'requester_name', 'message', 'item_url']
        },
        {
            'template_code': 'approval_decided',
            'name': 'Approval Decision',
            'description': 'Notification to the requester when a purchase request was approved or rejected',
            'subject_template': '{{item_type}} {{item_code}} {{decision}}: {{title}}',
            'body_template_html': '''
            <html>
            <body>
                <p>Dear {{user_name}},</p>
                <p><strong>{{item_type}} {{item_code}}</strong> ({{title}}) was {{decision}} by {{decided_by}}.</p>
                <p>{{note}}</p>
                <p><a href="{{item_url}}">Open</a></p>
                <p>Best regards,<br>Sampark</p>
            </body>
            </html>
            ''',
            'body_template_text': '''
            Dear {{user_name}},

            {{item_type}} {{item_code}} ({{title}}) was {{decision}} by {{decided_by}}.
            {{note}}

            Open: {{item_url}}

            Best regards,
            Sampark
            ''',
            'variables': ['user_name', 'item_type', 'item_code', 'title', 'decision', 'decided_by', 'note', 'item_url']
        }
    ]

    created_count = 0
    for template_data in templates:
        # Check if template already exists
        existing = (
            db.query(NotificationTemplate)
            .filter(NotificationTemplate.template_code == template_data['template_code'])
            .first()
        )
        
        if not existing:
            template = NotificationTemplate(
                id=uuid.uuid4(),
                tenant_id=None,  # System-wide
                **template_data
            )
            db.add(template)
            created_count += 1
        else:
            # Update existing template
            for key, value in template_data.items():
                setattr(existing, key, value)
    
    db.commit()
    return created_count


if __name__ == "__main__":
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        count = init_notification_templates(db)
        print(f"Created {count} notification templates")
    finally:
        db.close()

