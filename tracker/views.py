from django.contrib import messages
from django.db import transaction
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)
from django.utils import timezone

from .forms import (
    IncidentContactForm,
    IncidentDetailsForm,
    CaliforniaDetailsForm,
    SchoolIncidentForm,
    FormalSchoolComplaintForm,
    DemographicsImpactForm,
    FinalQuestionsForm,
    ReferralForm,
    AttachmentForm,
)

from .models import (
    IncidentReport,
    CaliforniaDetails,
    SchoolIncident,
    FormalSchoolComplaint,
    AffectedPersonDemographics,
    ReportOption,
)


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------

def location_includes_school(incident_form):
    """
    Determine whether 'school' was chosen as one of the location types.

    IMPORTANT:
    This assumes the school ReportOption has slug='school'.
    """

    if not incident_form.is_valid():
        return False

    location_types = incident_form.cleaned_data.get(
        "location_types"
    )

    if not location_types:
        return False

    return location_types.filter(
        slug="school"
    ).exists()


def should_show_school_form(
    state,
    incident_form,
    california_form=None,
):
    """
    School questions appear when either:

    1. The location includes "school", OR
    2. This is a California K-12 incident.
    """

    school_location = location_includes_school(
        incident_form
    )

    california_k12 = False

    if (
        state == "CA"
        and california_form
        and california_form.is_valid()
    ):
        california_k12 = bool(
            california_form.cleaned_data.get(
                "is_k12_incident"
            )
        )

    return school_location or california_k12


# ---------------------------------------------------------------------
# CREATE REPORT
# ---------------------------------------------------------------------

def incident_report_create(request):

    report = IncidentReport()

    if request.method == "POST":

        # ---------------------------------------------------------
        # Forms that always apply
        # ---------------------------------------------------------

        contact_form = IncidentContactForm(
            request.POST,
            instance=report,
            prefix="contact",
        )

        incident_form = IncidentDetailsForm(
            request.POST,
            instance=report,
            prefix="incident",
        )

        demographics_form = DemographicsImpactForm(
            request.POST,
            prefix="demographics",
        )

        final_form = FinalQuestionsForm(
            request.POST,
            instance=report,
            prefix="final",
        )

        attachment_form = AttachmentForm(
            request.POST,
            request.FILES,
            prefix="attachments",
        )

        # ---------------------------------------------------------
        # First validate the main forms.
        # ---------------------------------------------------------

        base_forms_valid = all([
            contact_form.is_valid(),
            incident_form.is_valid(),
            demographics_form.is_valid(),
            final_form.is_valid(),
            attachment_form.is_valid(),
        ])

        # We need state before determining conditional forms.
        state = contact_form.cleaned_data.get(
            "state"
        ) if contact_form.is_valid() else None

        # ---------------------------------------------------------
        # California conditional form
        # ---------------------------------------------------------

        california_form = None

        if state == "CA":
            california_form = CaliforniaDetailsForm(
                request.POST,
                prefix="california",
            )

            california_valid = california_form.is_valid()

        else:
            california_valid = True

        # ---------------------------------------------------------
        # School conditional form
        # ---------------------------------------------------------

        show_school = False

        if incident_form.is_valid():
            show_school = should_show_school_form(
                state,
                incident_form,
                california_form,
            )

        school_form = None

        if show_school:
            school_form = SchoolIncidentForm(
                request.POST,
                prefix="school",
            )

            school_valid = school_form.is_valid()

        else:
            school_valid = True

        # ---------------------------------------------------------
        # Formal CA complaint
        # ---------------------------------------------------------

        formal_complaint_form = None

        is_ca_k12 = False

        if (
            state == "CA"
            and california_form
            and california_form.is_valid()
        ):
            is_ca_k12 = bool(
                california_form.cleaned_data.get(
                    "is_k12_incident"
                )
            )

        if is_ca_k12:
            formal_complaint_form = FormalSchoolComplaintForm(
                request.POST,
                prefix="formal",
            )

            formal_valid = formal_complaint_form.is_valid()

        else:
            formal_valid = True

        # ---------------------------------------------------------
        # Referral form is CA-only
        # ---------------------------------------------------------

        referral_form = None

        if state == "CA":
            referral_form = ReferralForm(
                request.POST,
                prefix="referral",
            )

            referral_valid = referral_form.is_valid()

        else:
            referral_valid = True

        # ---------------------------------------------------------
        # Save everything atomically
        # ---------------------------------------------------------

        all_valid = all([
            base_forms_valid,
            california_valid,
            school_valid,
            formal_valid,
            referral_valid,
        ])

        if all_valid:

            with transaction.atomic():

                # Both forms edit IncidentReport.
                #
                # Save contact first, then copy the final/incident
                # values onto the same instance.

                report = contact_form.save(commit=False)

                incident_data = incident_form.cleaned_data

                incident_model_fields = [
                    "date_precision",
                    "incident_date",
                    "incident_month",
                    "incident_year",
                    "description",
                    "city",
                    "zip_code",
                    "anti_palestinian_racism",
                    "knows_of_other_apr_incidents",
                    "similar_incidents",
                    "previously_reported",
                    "resolution_steps",
                ]

                for field in incident_model_fields:
                    setattr(
                        report,
                        field,
                        incident_data.get(field),
                    )

                final_data = final_form.cleaned_data

                final_model_fields = [
                    "connection_change",
                    "other_identity_information",
                    "additional_information",
                    "support_sought_elsewhere",
                    "opt_out_of_followup",
                    "signature_name",
                    "signature_date",
                ]

                for field in final_model_fields:
                    setattr(
                        report,
                        field,
                        final_data.get(field),
                    )

                report.status = (
                    IncidentReport.Status.SUBMITTED
                )

                report.submitted_at = timezone.now()

                # Run model validation too.
                report.full_clean()

                report.save()

                # ---------------------------------------------
                # Multi-select incident options
                # ---------------------------------------------

                incident_form.save_options(report)

                # ---------------------------------------------
                # Demographics
                # ---------------------------------------------

                demographics = (
                    demographics_form.save(commit=False)
                )

                demographics.report = report
                demographics.save()

                demographics_form.save_options(report)

                # ---------------------------------------------
                # California
                # ---------------------------------------------

                if california_form:

                    california = (
                        california_form.save(commit=False)
                    )

                    california.report = report
                    california.save()

                # ---------------------------------------------
                # School
                # ---------------------------------------------

                if school_form:

                    school = school_form.save(
                        commit=False
                    )

                    school.report = report
                    school.save()

                    school_form.save_options(report)

                # ---------------------------------------------
                # Formal complaint
                # ---------------------------------------------

                if formal_complaint_form:

                    formal_complaint = (
                        formal_complaint_form.save(
                            commit=False
                        )
                    )

                    formal_complaint.report = report
                    formal_complaint.save()

                # ---------------------------------------------
                # Referrals
                # ---------------------------------------------

                if referral_form:
                    referral_form.save(report)

                # ---------------------------------------------
                # Attachments
                # ---------------------------------------------

                attachment_form.save(report)

            return redirect(
                "incident_report_success",
                uuid=report.uuid,
            )

    else:

        # ---------------------------------------------------------
        # GET
        # ---------------------------------------------------------

        contact_form = IncidentContactForm(
            prefix="contact",
        )

        incident_form = IncidentDetailsForm(
            prefix="incident",
        )

        california_form = CaliforniaDetailsForm(
            prefix="california",
        )

        school_form = SchoolIncidentForm(
            prefix="school",
        )

        formal_complaint_form = (
            FormalSchoolComplaintForm(
                prefix="formal",
            )
        )

        demographics_form = DemographicsImpactForm(
            prefix="demographics",
        )

        final_form = FinalQuestionsForm(
            prefix="final",
        )

        referral_form = ReferralForm(
            prefix="referral",
        )

        attachment_form = AttachmentForm(
            prefix="attachments",
        )

    context = {
        "contact_form": contact_form,
        "incident_form": incident_form,
        "california_form": california_form,
        "school_form": school_form,
        "formal_complaint_form": formal_complaint_form,
        "demographics_form": demographics_form,
        "final_form": final_form,
        "referral_form": referral_form,
        "attachment_form": attachment_form,
    }

    return render(
        request,
        "tracker/incident_report_form.html",
        context,
    )


# ---------------------------------------------------------------------
# SUCCESS
# ---------------------------------------------------------------------

def incident_report_success(request, uuid):

    report = get_object_or_404(
        IncidentReport,
        uuid=uuid,
        status=IncidentReport.Status.SUBMITTED,
    )

    return render(
        request,
        "tracker/incident_report_success.html",
        {
            "report": report,
        },
    )